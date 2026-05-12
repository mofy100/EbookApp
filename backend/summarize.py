"""
data/{id}/content_*.html を一括処理して要約を生成する
出力: data/{id}/summary.json

処理フロー:
  Step1: content_0.html, content_1.html, ... → 各contentのsummary（並列）
  Step2: 各summaryを順序結合 → 作品全体のsummary + tags（逐次）

使い方:
  python summarize_batch.py 10
  python summarize_batch.py 10 11 12
  python summarize_batch.py          # 全件
  python summarize_batch.py 10 --force

オプション:
  --data-dir   dataディレクトリのパス (default: data)
  --force      既存のsummary.jsonを上書きする
"""

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path

# ── 設定 ─────────────────────────────────────────────
MODEL = "qwen3.5:35b"
TAG_WHITELIST_PATH = "./backend/tags.json"
TEXT_MAX_CHARS = 100000
REQUEST_TIMEOUT = 300
REQUIRED_CATEGORIES = ["ジャンル", "時代", "文学運動・流派", "テーマ", "形式・文体"]

# SSH トンネル設定
# OLLAMA_SSH_HOST: リモートホスト（例: user@remote.example.com）
# OLLAMA_SSH_REMOTE_PORT: リモート側の Ollama ポート（デフォルト 11434）
# OLLAMA_LOCAL_PORT: ローカルにマッピングするポート（デフォルト 11434）
_OLLAMA_SSH_HOST = os.environ.get("OLLAMA_SSH_HOST", "")
_OLLAMA_SSH_REMOTE_PORT = int(os.environ.get("OLLAMA_SSH_REMOTE_PORT", "11434"))
_OLLAMA_LOCAL_PORT = int(os.environ.get("OLLAMA_LOCAL_PORT", "11434"))

OLLAMA_URL = f"http://localhost:{_OLLAMA_LOCAL_PORT}/api/chat"


# 見出しクラスのパターン
HEADING_CLASSES = ("o-midashi", "naka-midashi", "ko-midashi")


# ── HTML → テキスト ───────────────────────────────────
class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._headings: list[str] = []
        self._skip = False
        self._in_heading = False

    def _get_classes(self, attrs: list) -> set:
        for name, value in attrs:
            if name == "class" and value:
                return set(value.split())
        return set()

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "header", "footer"):
            self._skip = True
            return
        if self._get_classes(attrs) & set(HEADING_CLASSES):
            self._in_heading = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "header", "footer"):
            self._skip = False
            return
        if self._in_heading and tag == "p":
            self._in_heading = False
        if tag in ("p", "div", "br", "h1", "h2", "h3", "h4", "li"):
            self._parts.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        stripped = data.strip()
        if self._in_heading and stripped:
            self._parts.append(f"\n【見出し: {stripped}】\n")
            self._headings.append(stripped)
        else:
            self._parts.append(data)

    def get_text(self) -> str:
        raw = "".join(self._parts)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()

    def get_headings(self) -> list:
        return self._headings


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.get_text()


def html_to_text_with_headings(html: str) -> tuple:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.get_text(), parser.get_headings()


def content_sort_key(path: Path) -> int:
    """content_0.html → 0, content_10.html → 10 で数値ソート"""
    m = re.search(r"(\d+)", path.stem)
    return int(m.group(1)) if m else 0


# ── タグホワイトリスト ────────────────────────────────
def load_whitelist(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def build_tag_list(whitelist: dict) -> str:
    lines = []
    for category, tags in whitelist["categories"].items():
        lines.append(f"{category}: {', '.join(tags)}")
    return "\n".join(lines)

def build_tag_notes(whitelist: dict) -> str:
    lines = []
    for tag, note in whitelist.get("tag_notes", {}).items():
        lines.append(f"・{tag}: {note}")
    return "\n".join(lines)


# ── SSH トンネル ─────────────────────────────────────
@contextmanager
def ollama_ssh_tunnel():
    """OLLAMA_SSH_HOST が設定されている場合に SSH トンネルを張る。"""
    if not _OLLAMA_SSH_HOST:
        yield
        return

    cmd = [
        "ssh", "-N",
        "-L", f"{_OLLAMA_LOCAL_PORT}:localhost:{_OLLAMA_SSH_REMOTE_PORT}",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=30",
        _OLLAMA_SSH_HOST,
    ]
    print(f"SSHトンネル起動: {_OLLAMA_SSH_HOST} → localhost:{_OLLAMA_LOCAL_PORT}", file=sys.stderr)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # トンネル確立を最大15秒待つ
    for _ in range(30):
        if proc.poll() is not None:
            raise RuntimeError(f"SSHトンネルが異常終了しました (exit={proc.returncode})")
        try:
            with socket.create_connection(("localhost", _OLLAMA_LOCAL_PORT), timeout=1):
                break
        except OSError:
            time.sleep(0.5)
    else:
        proc.terminate()
        proc.wait()
        raise RuntimeError(f"SSHトンネル確立タイムアウト (localhost:{_OLLAMA_LOCAL_PORT})")

    print(f"SSHトンネル確立完了", file=sys.stderr)
    try:
        yield
    finally:
        proc.terminate()
        proc.wait()
        print("SSHトンネルを閉じました", file=sys.stderr)


# ── Ollama API 呼び出し ───────────────────────────────
def call_ollama(prompt: str, retries: int = 2) -> str:
    payload = json.dumps({
        "model": MODEL,
        "think": False,
        "stream": False,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                OLLAMA_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                body = json.loads(resp.read().decode("utf-8"))

            content = body["message"]["content"]
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
            content = content.strip()

            if not content:
                raise ValueError("モデルが空のレスポンスを返しました")

            return content

        except Exception as e:
            last_err = e
            if attempt < retries:
                print(f"    [retry {attempt+1}/{retries}] {e}", file=sys.stderr)

    raise RuntimeError(f"call_ollama 失敗 ({retries+1}回): {last_err}")


# ── JSON パース ───────────────────────────────────────
def parse_json(raw: str, fallback_key: str | None = None) -> dict:
    # fallback_key 指定時: JSONパース失敗でもプレーンテキストをそのまま返す
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    if not cleaned:
        raise ValueError(f"パース対象が空です。元のレスポンス: {repr(raw[:200])}")
    # モデルがf-stringエスケープ記法 {{ }} をそのまま出力した場合に修正
    cleaned = cleaned.replace("{{", "{").replace("}}", "}")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        if fallback_key:
            print(f"    [warn] JSONパース失敗。プレーンテキストを '{fallback_key}' として使用", file=sys.stderr)
            return {fallback_key: cleaned}
        raise ValueError(f"JSONパースエラー\n対象文字列: {repr(cleaned[:300])}")

def normalize_tags(tags) -> dict:
    if isinstance(tags, list):
        return {"(未分類)": tags}
    if isinstance(tags, dict):
        for cat in REQUIRED_CATEGORIES:
            if cat not in tags:
                tags[cat] = []
        for cat, values in tags.items():
            if not isinstance(values, list):
                tags[cat] = [values] if values else []
        return tags
    return {cat: [] for cat in REQUIRED_CATEGORIES}


# ── Step1: content単位の要約 ──────────────────────────
def summarize_content(html_path: Path, prev_summary: str = "") -> dict:
    """
    1つのcontentファイルを要約する（タグなし）。
    prev_summary: 直前のcontentの要約（語り手・文脈の継続性を保つため）
    """
    html = html_path.read_text(encoding="utf-8", errors="ignore")
    text, headings = html_to_text_with_headings(html)
    text = text[:TEXT_MAX_CHARS]

    if not text.strip():
        return {"summary": "(テキストが空のため要約スキップ)", "headings": []}

    # 直前の要約がある場合のみ文脈セクションを追加
    context_section = ""
    if prev_summary:
        context_section = f"""
## 直前のパートの要約（文脈参照用）
{prev_summary}

"""

    prompt = f"""
あなたは日本文学に精通した書評家です。
以下の小説テキストの一部を読み、この箇所の内容を要約してください。
直前のパートの要約が提供されている場合は、語り手・登場人物・状況の継続性を踏まえて読んでください。
{context_section}
## 要約
200〜400字で以下を含めてください：
- この部分のあらすじ（ネタバレなし、曖昧な表現を避ける）
- 描かれている心情・状況・展開のポイント
- 語り手や視点に変化があれば明記すること

## 出力
JSON形式（説明文・マークダウン不要）:
{{
    "summary": "300〜500字の要約をここに"
}}

## テキスト
{text}
"""

    raw = call_ollama(prompt)
    data = parse_json(raw, fallback_key="summary")
    return {"headings": headings, "summary": data.get("summary", "")}


# ── Step2: 作品全体の統合要約 ─────────────────────────
def summarize_overall(contents: dict, whitelist: dict) -> dict:
    """
    各contentのsummaryを順序通りに結合し、作品全体の要約とタグを生成する。
    contents: {"content_0.html": {"summary": "..."}, ...} （順序保証済み）
    """
    tag_list  = build_tag_list(whitelist)
    tag_notes = build_tag_notes(whitelist)

    parts = []
    for i, (filename, data) in enumerate(contents.items()):
        parts.append(f"【パート{i}】\n{data['summary']}")
    combined = "\n\n".join(parts)

    prompt = f"""
あなたは日本文学に精通した書評家です。
以下は、ある小説を複数のパートに分けて要約したものです。
これらを統合して、作品全体の解説文とタグを生成してください。

## 解説文のルール
500字前後で以下をすべて含めてください：
- あらすじ（ネタバレなし・核心的な結末には触れない）
- 作品の主題・テーマ
- 読みどころ・この作品ならではの魅力

## タグ選択ルール
- 下記ホワイトリストに含まれるタグのみを選ぶこと（それ以外は使用禁止）
- 3〜8個を目安に選択する
- 複数カテゴリから選んでよい

### タグホワイトリスト
{tag_list}

### タグ使用上の注意
{tag_notes}

## 出力
JSON形式（説明文・マークダウン不要）:
{{
    "summary": "500字前後の解説文をここに",
    "tags": {{
        "ジャンル": ["tag1"],
        "時代": [],
        "文学運動・流派": [],
        "テーマ": ["tag2", "tag3"],
        "形式・文体": []
    }}
}}

tagsは必ず上記のカテゴリキーをすべて含めること。該当なしは空配列[]にすること。

## 各パートの要約
{combined}
"""

    raw = call_ollama(prompt)
    data = parse_json(raw, fallback_key="summary")
    data["tags"] = normalize_tags(data.get("tags", {}))
    return data


# ── 1ディレクトリの処理 ──────────────────────────────
def process_book(book_dir: Path, whitelist: dict, force: bool) -> dict:
    book_id = book_dir.name
    out_path = book_dir / "summary.json"

    if out_path.exists() and not force:
        return {"id": book_id, "status": "skip", "message": "既存のsummary.jsonをスキップ"}

    html_files = sorted(book_dir.glob("content_*.html"), key=content_sort_key)
    if not html_files:
        return {"id": book_id, "status": "skip", "message": "content_*.html が見つからない"}

    # ── Step1: content単位の要約（逐次・前文脈を引き継ぐ） ──
    print(f"  [{book_id}] Step1: {len(html_files)} ファイルを逐次要約中...")
    ordered_contents: dict[str, dict] = {}
    errors: list[str] = []

    EMPTY_CONTENT = {"summary": ""}
    prev_summary = ""  # 直前contentの要約（最初は空）

    for p in html_files:
        try:
            result = summarize_content(p, prev_summary=prev_summary)
            ordered_contents[p.name] = result
            prev_summary = result["summary"]  # 次のcontentへ引き継ぐ
            print(f"    [ok] {book_id}/{p.name}")
        except Exception as e:
            ordered_contents[p.name] = EMPTY_CONTENT
            errors.append(p.name)
            prev_summary = ""  # 失敗時はリセット
            print(f"    [error] {book_id}/{p.name}: {e}", file=sys.stderr)

    # ── Step2: 作品全体の統合要約（逐次） ───────────────
    # 失敗したcontentがある場合はoverallを空にする（2）
    EMPTY_OVERALL = {"summary": "", "tags": {cat: [] for cat in REQUIRED_CATEGORIES}}

    if errors:
        overall = EMPTY_OVERALL
        print(f"  [{book_id}] Step2: スキップ（失敗content {len(errors)}件: {errors}）")
    else:
        print(f"  [{book_id}] Step2: 統合要約を生成中...")
        try:
            overall = summarize_overall(ordered_contents, whitelist)
            print(f"    [ok] {book_id}/overall")
        except Exception as e:
            overall = EMPTY_OVERALL
            print(f"    [error] {book_id}/overall: {e}", file=sys.stderr)

    # ── 出力 ─────────────────────────────────────────────
    result = {
        "contents": ordered_contents,
        "overall": overall,
    }
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    ok_count = len(html_files) - len(errors)
    msg = f"Step1: {ok_count}/{len(html_files)} 完了"
    if errors:
        msg += f" / 失敗(空): {errors} / Step2: スキップ"
    else:
        msg += " / Step2: overall 生成済み"
    status = "ok" if not errors else "partial"
    return {"id": book_id, "status": status, "message": msg}


# ── メイン ───────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="*", help="処理するID（例: 10 11 12）省略時は全件")
    parser.add_argument("--data-dir", default="backend/data", help="dataディレクトリのパス")
    parser.add_argument("--force", action="store_true", help="既存のsummary.jsonを上書き")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"[error] データディレクトリが見つかりません: {data_dir}", file=sys.stderr)
        sys.exit(1)

    whitelist = load_whitelist(TAG_WHITELIST_PATH)

    if args.ids:
        book_dirs = []
        for id_ in args.ids:
            d = data_dir / id_
            if not d.is_dir():
                print(f"[warn] 存在しないディレクトリをスキップ: {d}", file=sys.stderr)
            else:
                book_dirs.append(d)
        book_dirs = sorted(book_dirs)
    else:
        book_dirs = sorted(d for d in data_dir.iterdir() if d.is_dir())

    if not book_dirs:
        print("[error] 処理対象のディレクトリが見つかりません", file=sys.stderr)
        sys.exit(1)

    print(f"対象: {len(book_dirs)} ディレクトリ / force={args.force}")
    print("-" * 50)

    ok = skip = error = 0

    with ollama_ssh_tunnel():
        for book_dir in book_dirs:
            res = process_book(book_dir, whitelist, args.force)
            print(f"[{res['status'].upper():5s}] {res['id']}: {res['message']}")
            if res["status"] == "ok":        ok += 1
            elif res["status"] == "skip":    skip += 1
            elif res["status"] == "partial": error += 1
            else:                            error += 1

    print("-" * 50)
    print(f"完了: ok={ok}  skip={skip}  error={error}")


if __name__ == "__main__":
    main()
