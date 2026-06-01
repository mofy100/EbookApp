"""
data/{id}/content_*.html を一括処理して要約を生成する
出力: data/{id}/summary_qwen.json

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
  --force      既存のsummary_qwen.jsonを上書きする
"""

import argparse
import http.client
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path

# ── 設定 ─────────────────────────────────────────────
MODEL = "qwen3.5:35b"
TAG_WHITELIST_PATH = "./backend/tags.json"
TEXT_MAX_CHARS = 100000
REQUEST_TIMEOUT = 300
REQUIRED_CATEGORIES = ["ジャンル", "サブジャンル", "時代", "文学運動・流派", "テーマ", "形式・文体"]

# SearXNG 設定
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8080/search")
SEARXNG_TIMEOUT = 10
SEARXNG_MAX_RESULTS = 3   # 1クエリあたりの取得件数
SEARXNG_SNIPPET_CHARS = 300  # 1件あたりの本文上限（トークン節約）
SEARXNG_TOTAL_CHARS = 4000   # Qwenに渡す検索結果テキストの上限

# SSH トンネル設定
# OLLAMA_SSH_HOST: リモートホスト（例: user@remote.example.com）
# OLLAMA_SSH_REMOTE_PORT: リモート側の Ollama ポート（デフォルト 11434）
# OLLAMA_LOCAL_PORT: ローカルにマッピングするポート（デフォルト 11434）
_OLLAMA_SSH_HOST = os.environ.get("OLLAMA_SSH_HOST", "")
_OLLAMA_SSH_REMOTE_PORT = int(os.environ.get("OLLAMA_SSH_REMOTE_PORT", "11434"))
_OLLAMA_LOCAL_PORT = int(os.environ.get("OLLAMA_LOCAL_PORT", "11434"))

OLLAMA_URL = f"http://localhost:{_OLLAMA_LOCAL_PORT}/api/chat"


class OllamaConnectionError(Exception):
    """Ollamaへのネットワーク接続が切断された場合に発生する例外。"""


def _is_connection_error(e: Exception) -> bool:
    return isinstance(e, (
        urllib.error.URLError,
        ConnectionError,
        http.client.RemoteDisconnected,
    ))


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
            if _is_connection_error(e):
                raise OllamaConnectionError(f"Ollamaへの接続が切れました: {e}") from e
            last_err = e
            if attempt < retries:
                print(f"    [retry {attempt+1}/{retries}] {e}", file=sys.stderr)

    raise RuntimeError(f"call_ollama 失敗 ({retries+1}回): {last_err}")


# ── JSON パース ───────────────────────────────────────
def _extract_balanced_braces(text: str) -> str | None:
    """先頭の { から対応する閉じ } までを抽出する。"""
    if not text.startswith("{"):
        return None
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[: i + 1]
    return None


def _regex_extract(text: str) -> dict:
    """JSONパース失敗時に "summary" と "tags" を正規表現で個別抽出する。"""
    result: dict = {}

    m_sum = re.search(r'"summary"\s*:\s*"', text)
    if not m_sum:
        return result

    body_start = m_sum.end()
    m_tags = re.search(r'"tags"\s*:', text[body_start:])

    if m_tags:
        tags_abs = body_start + m_tags.start()
        # summary本文: body_startからtagsキーの手前まで（末尾の ",\s* を除去）
        raw_summary = re.sub(r'["\s,]+$', "", text[body_start:tags_abs])
        result["summary"] = raw_summary

        tags_val_start = body_start + m_tags.end()
        block = _extract_balanced_braces(text[tags_val_start:].lstrip())
        if block:
            try:
                result["tags"] = json.loads(block)
            except json.JSONDecodeError:
                pass
    else:
        # tagsが見つからない場合はsummaryのみ
        result["summary"] = re.sub(r'["\s}]+$', "", text[body_start:])

    return result


def parse_json(raw: str, fallback_key: str | None = None) -> dict:
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    # 【出力】【解説文】 などのプレフィックスを除去
    cleaned = re.sub(r"^【[^】]*】\s*", "", cleaned)
    if not cleaned:
        raise ValueError(f"パース対象が空です。元のレスポンス: {repr(raw[:200])}")
    # モデルがf-stringエスケープ記法 {{ }} をそのまま出力した場合に修正
    cleaned = cleaned.replace("{{", "{").replace("}}", "}")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 正規表現でsummary/tagsを個別抽出（fallbackより先に試みる）
        extracted = _regex_extract(cleaned)
        if extracted.get("summary"):
            print(
                f"    [warn] JSONパース失敗→regex抽出で復元 (keys={list(extracted)})",
                file=sys.stderr,
            )
            return extracted
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


# ── SearXNG Web検索 ───────────────────────────────────
def web_search(query: str, num_results: int = SEARXNG_MAX_RESULTS) -> list[dict]:
    """
    SearXNG JSON APIに問い合わせ、結果リストを返す。
    失敗時は空リストを返し、呼び出し元の処理を継続させる。
    """
    params = urllib.parse.urlencode({
        "q":          query,
        "format":     "json",
        "language":   "ja-JP",
        "safesearch": 0,
    })
    url = f"{SEARXNG_URL}?{params}"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "summarize-bot/1.0"},
        )
        with urllib.request.urlopen(req, timeout=SEARXNG_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = data.get("results", [])[:num_results]
        return [
            {
                "title":   r.get("title", ""),
                "url":     r.get("url", ""),
                "content": r.get("content", "")[:SEARXNG_SNIPPET_CHARS],
            }
            for r in results
            if r.get("content")   # 本文が空のものは除外
        ]
    except Exception as e:
        print(f"    [web_search error] query={repr(query)} / {e}", file=sys.stderr)
        return []


def fetch_literary_background(title: str, author: str) -> str:
    """
    タイトル・著者名でSearXNGを使いWeb検索し、
    Qwenで200字程度の文学的背景テキストにまとめて返す。
    タイトル・著者が両方空、または検索結果が0件の場合は空文字を返す。
    """
    if not title and not author:
        return ""

    subject = f"{author}　{title}".strip()
    queries = [
        f"{subject} 解説 文学的評価",
        f"{author} 作風 時代背景 文学運動",
    ]

    snippets: list[str] = []
    for q in queries:
        for r in web_search(q):
            snippets.append(f"【{r['title']}】\n{r['content']}")

    if not snippets:
        print(f"    [web_search] 検索結果なし: {subject}", file=sys.stderr)
        return ""

    raw_text = "\n\n".join(snippets)[:SEARXNG_TOTAL_CHARS]
    print(f"    [web_search] 背景情報取得: {len(snippets)}件 ({len(raw_text)}字)", file=sys.stderr)

    prompt = f"""
あなたは日本文学の専門家です。
以下はWeb検索で得た「{title}」（{author}著）に関する情報です。
文学的位置づけ・時代背景・批評的評価を200字程度で日本語にまとめてください。

## 検索結果
{raw_text}

## 出力
JSON形式（説明文・マークダウン不要）:
{{
    "background": "200字程度のまとめ"
}}
"""
    try:
        raw = call_ollama(prompt)
        data = parse_json(raw, fallback_key="background")
        return data.get("background", "")
    except Exception as e:
        print(f"    [web_search] 背景まとめ生成失敗: {e}", file=sys.stderr)
        return ""


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
def summarize_overall(contents: dict, whitelist: dict, title: str = "", author: str = "") -> dict:
    """
    各contentのsummaryを順序通りに結合し、作品全体の要約とタグを生成する。
    contents: {"content_0.html": {"summary": "..."}, ...} （順序保証済み）
    SearXNGが利用可能な場合は文学的背景をWeb検索で補強する。
    """
    tag_list  = build_tag_list(whitelist)
    tag_notes = build_tag_notes(whitelist)

    parts = []
    for i, (filename, data) in enumerate(contents.items()):
        parts.append(f"【パート{i}】\n{data['summary']}")
    combined = "\n\n".join(parts)

    work_info = ""
    if title or author:
        work_info = f"\n## 作品情報\n"
        if title:
            work_info += f"タイトル: {title}\n"
        if author:
            work_info += f"著者: {author}\n"

    # ── Web検索で文学的背景を補強 ─────────────────────
    background = fetch_literary_background(title, author)
    background_section = ""
    if background:
        background_section = f"""
## 文学的背景（Web検索による参考情報）
{background}
参考情報は解説文の文脈・タグ選択に活かしてください。ただし検索結果の誤りには注意し、本文の要約を優先してください。
"""

    prompt = f"""
あなたは日本文学に精通した書評家です。
以下は、ある小説を複数のパートに分けて要約したものです。
これらを統合して、作品全体の解説文とタグを生成してください。
{work_info}{background_section}

## 解説文のルール
500字前後で以下をすべて含めてください：
- あらすじ（ネタバレなし・核心的な結末には触れない）
- 作品の主題・テーマ
- 読みどころ・この作品ならではの魅力

## タグ選択ルール
- 下記ホワイトリストに含まれるタグのみを選ぶこと（それ以外は使用禁止）
- ジャンルは1作品につき1つだけ選択すること
- サブジャンル・テーマは複数選択可（サブジャンル＋テーマ合計で3〜7個を目安）
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
        "サブジャンル": ["tag2"],
        "時代": [],
        "文学運動・流派": [],
        "テーマ": ["tag3", "tag4"],
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
    out_path = book_dir / "summary_qwen.json"

    if out_path.exists() and not force:
        return {"id": book_id, "status": "skip", "message": "既存のsummary_qwen.jsonをスキップ"}

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
        except OllamaConnectionError:
            raise
        except Exception as e:
            ordered_contents[p.name] = EMPTY_CONTENT
            errors.append(p.name)
            prev_summary = ""  # 失敗時はリセット
            print(f"    [error] {book_id}/{p.name}: {e}", file=sys.stderr)

    # ── Step1 失敗時はスキップ ────────────────────────────
    if errors:
        print(f"  [{book_id}] Step2: スキップ（失敗content {len(errors)}件: {errors}）")
        ok_count = len(html_files) - len(errors)
        return {
            "id": book_id,
            "status": "error",
            "message": f"Step1: {ok_count}/{len(html_files)} 完了 / 失敗: {errors} / summary_qwen.json 未作成",
        }

    # ── manifest.json から作品名・著者名を取得 ──────────
    title = author = ""
    manifest_path = book_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            title  = manifest.get("title", "")
            author = manifest.get("author", "")
        except Exception:
            pass

    # ── Step2: 作品全体の統合要約（逐次） ───────────────
    print(f"  [{book_id}] Step2: 統合要約を生成中...")
    try:
        overall = summarize_overall(ordered_contents, whitelist, title=title, author=author)
        print(f"    [ok] {book_id}/overall")
    except OllamaConnectionError:
        raise
    except Exception as e:
        print(f"    [error] {book_id}/overall: {e}", file=sys.stderr)
        return {
            "id": book_id,
            "status": "error",
            "message": f"Step2 失敗: {e} / summary_qwen.json 未作成",
        }

    # ── 出力 ─────────────────────────────────────────────
    result = {
        "contents": ordered_contents,
        "overall": overall,
    }
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    return {
        "id": book_id,
        "status": "ok",
        "message": f"Step1: {len(html_files)}/{len(html_files)} 完了 / Step2: overall 生成済み",
    }


# ── メイン ───────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="*", help="処理するID（例: 10 11 12）省略時は全件")
    parser.add_argument("--data-dir", default="backend/data", help="dataディレクトリのパス")
    parser.add_argument("--force", action="store_true", help="既存のsummary_qwen.jsonを上書き")
    parser.add_argument(
        "--no-search",
        action="store_true",
        help="SearXNGによるWeb検索をスキップする（オフライン時・高速化用）",
    )
    args = parser.parse_args()

    # --no-search が指定された場合は web_search 関数を無効化
    if args.no_search:
        global web_search
        def web_search(query, num_results=SEARXNG_MAX_RESULTS):  # noqa: F811
            return []
        print("[info] --no-search: Web検索を無効化しました", file=sys.stderr)

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
            try:
                res = process_book(book_dir, whitelist, args.force)
            except OllamaConnectionError as e:
                print(f"\n[fatal] {e}", file=sys.stderr)
                print(f"完了: ok={ok}  skip={skip}  error={error}  (接続切断により中断)", file=sys.stderr)
                sys.exit(1)
            print(f"[{res['status'].upper():5s}] {res['id']}: {res['message']}")
            if res["status"] == "ok":        ok += 1
            elif res["status"] == "skip":    skip += 1
            elif res["status"] == "partial": error += 1
            else:                            error += 1

    print("-" * 50)
    print(f"完了: ok={ok}  skip={skip}  error={error}")


if __name__ == "__main__":
    main()