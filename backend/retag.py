"""
既存の summary_qwen.json の overall.summary をもとに tags を AI で再生成する。
summary フィールドはそのまま保持し、overall.tags のみ上書きする。

処理フロー:
  1. summary_qwen.json の overall.summary を読む
  2. manifest.json からタイトル・著者を取得
  3. LLM にプロンプトを送り tags を生成
  4. overall.tags のみ更新して保存

  ※ 実行後に book_tags テーブルを反映するには
     POST /api/admin/sync-tags を叩くか、サーバーを再起動すること。

使い方:
  python retag.py 10
  python retag.py 10 11 12
  python retag.py          # 全件（tags 未設定のもののみ）
  python retag.py --force  # 全件（既存 tags を上書き）
  python retag.py 10 --dry-run  # プロンプトを確認（LLM 不使用）

オプション:
  --data-dir   dataディレクトリのパス (default: backend/data)
  --force      既存の tags を上書きする
  --dry-run    LLM を呼ばずプロンプトのみ標準出力に表示する
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
import urllib.request
from contextlib import contextmanager
from pathlib import Path

# ── 設定 ─────────────────────────────────────────────
MODEL             = "qwen3.5:35b"
TAG_WHITELIST_PATH = "./backend/tags.json"
REQUEST_TIMEOUT   = 120
REQUIRED_CATEGORIES = ["ジャンル", "時代", "文学運動・流派", "テーマ", "形式・文体"]

# 文字数から自動付与するため AI に選ばせないタグ
AUTO_ASSIGNED_TAGS = {"掌編小説", "短編小説", "中編小説", "長編小説"}

# SSH トンネル設定（summarize.py と共通）
_OLLAMA_SSH_HOST        = os.environ.get("OLLAMA_SSH_HOST", "")
_OLLAMA_SSH_REMOTE_PORT = int(os.environ.get("OLLAMA_SSH_REMOTE_PORT", "11434"))
_OLLAMA_LOCAL_PORT      = int(os.environ.get("OLLAMA_LOCAL_PORT", "11434"))
OLLAMA_URL = f"http://localhost:{_OLLAMA_LOCAL_PORT}/api/chat"


# ── 例外 ─────────────────────────────────────────────
class OllamaConnectionError(Exception):
    pass


def _is_connection_error(e: Exception) -> bool:
    return isinstance(e, (
        urllib.error.URLError,
        ConnectionError,
        http.client.RemoteDisconnected,
    ))


# ── SSH トンネル ─────────────────────────────────────
@contextmanager
def ollama_ssh_tunnel():
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

    print("SSHトンネル確立完了", file=sys.stderr)
    try:
        yield
    finally:
        proc.terminate()
        proc.wait()
        print("SSHトンネルを閉じました", file=sys.stderr)


# ── Ollama API ────────────────────────────────────────
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
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
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


def parse_json_tags(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    cleaned = re.sub(r"^【[^】]*】\s*", "", cleaned)
    cleaned = cleaned.replace("{{", "{").replace("}}", "}")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{", cleaned)
        if m:
            block = _extract_balanced_braces(cleaned[m.start():])
            if block:
                try:
                    return json.loads(block)
                except json.JSONDecodeError:
                    pass
        raise ValueError(f"JSONパースエラー: {repr(cleaned[:300])}")


def normalize_tags(tags) -> dict:
    if isinstance(tags, list):
        return {"(未分類)": tags}
    if isinstance(tags, dict):
        for cat in REQUIRED_CATEGORIES:
            if cat not in tags:
                tags[cat] = []
        for cat, values in list(tags.items()):
            if not isinstance(values, list):
                tags[cat] = [values] if values else []
        return tags
    return {cat: [] for cat in REQUIRED_CATEGORIES}


# ── タグホワイトリスト ────────────────────────────────
def load_whitelist(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_tag_list(whitelist: dict) -> str:
    """AUTO_ASSIGNED_TAGS を除いたホワイトリスト文字列を生成する。"""
    lines = []
    for category, tags in whitelist["categories"].items():
        filtered = [t for t in tags if t not in AUTO_ASSIGNED_TAGS]
        if filtered:
            lines.append(f"{category}: {', '.join(filtered)}")
    return "\n".join(lines)


def build_tag_notes(whitelist: dict) -> str:
    lines = []
    for tag, note in whitelist.get("tag_notes", {}).items():
        lines.append(f"・{tag}: {note}")
    return "\n".join(lines)


# ── プロンプト ────────────────────────────────────────
def build_prompt(summary: str, title: str, author: str, whitelist: dict) -> str:
    tag_list  = build_tag_list(whitelist)
    tag_notes = build_tag_notes(whitelist)

    work_info = ""
    if title or author:
        work_info = f"タイトル: {title}\n著者: {author}\n\n"

    return f"""あなたは日本文学に精通した書評家です。
以下の作品解説をもとに、この作品に最適なタグをホワイトリストから選んでください。

## 作品情報
{work_info}## 作品解説
{summary}

## タグ選択ルール
- 下記ホワイトリストに含まれるタグのみを使用すること（それ以外は使用禁止）
- 3〜8個を目安に選択する
- 複数カテゴリから選んでよい
- 作品の主題・文体・時代・流派を踏まえて選ぶこと

### タグホワイトリスト
{tag_list}

### タグ使用上の注意
{tag_notes}

## 出力
JSON形式のみ（説明文・マークダウン・コードブロック不要）:
{{
    "ジャンル": [],
    "時代": [],
    "文学運動・流派": [],
    "テーマ": [],
    "形式・文体": []
}}

すべてのカテゴリキーを必ず含めること。該当なしは空配列 [] にすること。
"""


# ── 1作品の処理 ──────────────────────────────────────
def retag_book(book_dir: Path, whitelist: dict, force: bool, dry_run: bool) -> dict:
    book_id  = book_dir.name
    json_path = book_dir / "summary_qwen.json"

    if not json_path.exists():
        return {"id": book_id, "status": "skip", "message": "summary_qwen.json が存在しない"}

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"id": book_id, "status": "error", "message": f"JSON読み込み失敗: {e}"}

    overall = data.get("overall", {})
    summary = overall.get("summary", "")
    if not summary.strip():
        return {"id": book_id, "status": "skip", "message": "overall.summary が空"}

    # 既存 tags がある場合は --force がないとスキップ
    existing_tags = overall.get("tags", {})
    has_tags = (
        isinstance(existing_tags, dict)
        and any(isinstance(v, list) and v for v in existing_tags.values())
    )
    if has_tags and not force:
        return {"id": book_id, "status": "skip", "message": "tags 既存（--force で上書き可）"}

    # manifest.json からタイトル・著者を取得
    title = author = ""
    manifest_path = book_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            title  = manifest.get("title", "")
            author = manifest.get("author", "")
        except Exception:
            pass

    prompt = build_prompt(summary, title, author, whitelist)

    # --dry-run: プロンプトを表示して終了
    if dry_run:
        print(f"\n{'=' * 60}")
        print(f"[DRY-RUN] id={book_id}  {title} / {author}")
        print("=" * 60)
        print(prompt)
        return {"id": book_id, "status": "dry-run", "message": "プロンプトを表示（LLM 不使用）"}

    # LLM 呼び出し → タグ生成
    try:
        raw      = call_ollama(prompt)
        tags_raw = parse_json_tags(raw)
        new_tags = normalize_tags(tags_raw)
    except OllamaConnectionError:
        raise
    except Exception as e:
        return {"id": book_id, "status": "error", "message": f"LLM/パース失敗: {e}"}

    # overall.tags のみ更新（summary・contents は保持）
    data["overall"]["tags"] = new_tags
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    tag_count = sum(len(v) for v in new_tags.values() if isinstance(v, list))
    return {"id": book_id, "status": "ok", "message": f"{tag_count}個のタグを生成"}


# ── メイン ───────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="summary_qwen.json のタグを AI で再生成する")
    parser.add_argument("ids",       nargs="*",        help="処理するID（省略時は全件）")
    parser.add_argument("--data-dir", default="backend/data")
    parser.add_argument("--force",    action="store_true", help="既存 tags を上書き")
    parser.add_argument("--dry-run",  action="store_true", help="プロンプトのみ表示（LLM 不使用）")
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
            if d.is_dir():
                book_dirs.append(d)
            else:
                print(f"[warn] 存在しないディレクトリをスキップ: {d}", file=sys.stderr)
        book_dirs = sorted(book_dirs)
    else:
        book_dirs = sorted(d for d in data_dir.iterdir() if d.is_dir())

    if not book_dirs:
        print("[error] 処理対象のディレクトリが見つかりません", file=sys.stderr)
        sys.exit(1)

    mode = "dry-run" if args.dry_run else ("force" if args.force else "通常")
    print(f"対象: {len(book_dirs)} ディレクトリ / モード: {mode}")
    print("-" * 50)

    ok = skip = error = 0

    with ollama_ssh_tunnel():
        for book_dir in book_dirs:
            try:
                res = retag_book(book_dir, whitelist, args.force, args.dry_run)
            except OllamaConnectionError as e:
                print(f"\n[fatal] {e}", file=sys.stderr)
                print(f"完了: ok={ok}  skip={skip}  error={error}  (接続切断により中断)", file=sys.stderr)
                sys.exit(1)

            label = res["status"].upper()
            print(f"[{label:7s}] {res['id']}: {res['message']}")
            if   res["status"] == "ok":      ok    += 1
            elif res["status"] == "skip":    skip  += 1
            elif res["status"] == "dry-run": ok    += 1
            else:                            error += 1

    print("-" * 50)
    print(f"完了: ok={ok}  skip={skip}  error={error}")
    if not args.dry_run and ok > 0:
        print("→ book_tags テーブルの反映: POST /api/admin/sync-tags またはサーバー再起動")


if __name__ == "__main__":
    main()
