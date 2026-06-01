"""
books_data/{id}/manifest.json のタイトル・著者名をもとに SearXNG でWeb検索し、
文学的背景(background)を Ollama で要約して summary_web.json として保存する。

処理フロー:
  1. manifest.json から title / author を取得
  2. SearXNG JSON API で複数クエリを検索
  3. 検索スニペットを Ollama に渡して background を生成
  4.books_data/{id}/summary_web.json に保存

使い方:
  python summarize_web.py 10
  python summarize_web.py 10 11 12
  python summarize_web.py          # 全件
  python summarize_web.py 10 --force

オプション:
  --data-dir   dataディレクトリのパス (default: backend/books_data)
  --force      既存の summary_web.json を上書きする
  --searxng    SearXNG の URL (default: http://localhost:8080)
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
from pathlib import Path

# ── 設定 ─────────────────────────────────────────────
MODEL           = "qwen3.5:35b"
REQUEST_TIMEOUT = 120
SEARCH_RESULTS  = 5       # クエリあたりの検索結果数
SNIPPET_MAX     = 8000    # Ollamaへ渡すスニペットの最大文字数

# SSH トンネル設定（既存スクリプトと共通）
_OLLAMA_SSH_HOST        = os.environ.get("OLLAMA_SSH_HOST", "")
_OLLAMA_SSH_REMOTE_PORT = int(os.environ.get("OLLAMA_SSH_REMOTE_PORT", "11434"))
_OLLAMA_LOCAL_PORT      = int(os.environ.get("OLLAMA_LOCAL_PORT", "11434"))
OLLAMA_URL              = f"http://localhost:{_OLLAMA_LOCAL_PORT}/api/chat"


# ── 例外 ─────────────────────────────────────────────
class OllamaConnectionError(Exception):
    pass


def _is_connection_error(e: Exception) -> bool:
    return isinstance(e, (
        urllib.error.URLError,
        ConnectionError,
        http.client.RemoteDisconnected,
    ))


# ── SSH トンネル（既存スクリプトから流用） ────────────
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


# ── Ollama 呼び出し ───────────────────────────────────
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


# ── SearXNG Web検索 ───────────────────────────────────
def web_search(query: str, searxng_url: str, num_results: int = SEARCH_RESULTS) -> list[dict]:
    """SearXNG JSON API に問い合わせ、スニペットリストを返す。失敗時は空リスト。"""
    params = urllib.parse.urlencode({
        "q":          query,
        "format":     "json",
        "language":   "ja",
        "safesearch": 0,
    })
    url = f"{searxng_url}/search?{params}"

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "summarize-web-bot/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = data.get("results", [])[:num_results]
        return [
            {
                "title":   r.get("title", ""),
                "url":     r.get("url", ""),
                "content": r.get("content", ""),
            }
            for r in results
            if r.get("content")
        ]
    except Exception as e:
        print(f"    [web_search error] {e}", file=sys.stderr)
        return []


def collect_snippets(title: str, author: str, searxng_url: str) -> str:
    """複数クエリで検索し、スニペットを結合して返す。"""
    queries = [
        f"{author} {title} 解説 あらすじ",
        f"{author} {title} 文学的評価 批評",
        f"{author} 作風 時代背景 文学運動",
    ]

    snippets: list[str] = []
    for q in queries:
        results = web_search(q, searxng_url)
        for r in results:
            snippets.append(f"【{r['title']}】\n{r['content']}")
        if snippets:
            print(f"    [search] '{q}' → {len(results)} 件", file=sys.stderr)

    return "\n\n".join(snippets)[:SNIPPET_MAX]


# ── background 生成 ───────────────────────────────────
def generate_background(title: str, author: str, snippets: str) -> str:
    """検索スニペットをもとに Ollama で background テキストを生成する。"""
    prompt = f"""
あなたは日本文学に精通した書評家です。
以下はWeb検索で得た「{title}」（{author}著）に関する情報です。

これらをもとに、作品の文学的背景・評価・時代背景・著者の作風を
300〜500字の日本語でまとめてください。

## 出力
JSON形式のみで返すこと（説明文・マークダウン不要）:
{{
    "background": "300〜500字のまとめをここに"
}}

## 検索結果
{snippets}
"""
    raw = call_ollama(prompt)

    # JSONを抽出
    match = re.search(r'\{.*\}', raw, flags=re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            return data.get("background", "").strip()
        except json.JSONDecodeError:
            pass

    # フォールバック: テキストをそのまま返す
    return raw.strip()


# ── 1ディレクトリの処理 ──────────────────────────────
def process_book(book_dir: Path, searxng_url: str, force: bool) -> dict:
    book_id  = book_dir.name
    out_path = book_dir / "summary_web.json"

    if out_path.exists() and not force:
        return {"id": book_id, "status": "skip", "message": "既存の summary_web.json をスキップ"}

    # manifest.json から title / author を取得
    manifest_path = book_dir / "manifest.json"
    if not manifest_path.exists():
        return {"id": book_id, "status": "skip", "message": "manifest.json が見つからない"}

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        title  = manifest.get("title", "").strip()
        author = manifest.get("author", "").strip()
    except Exception as e:
        return {"id": book_id, "status": "error", "message": f"manifest.json 読み込み失敗: {e}"}

    if not title and not author:
        return {"id": book_id, "status": "skip", "message": "title / author が空のためスキップ"}

    print(f"  [{book_id}] 検索中: 『{title}』 / {author}")

    # Web検索
    snippets = collect_snippets(title, author, searxng_url)
    if not snippets:
        return {"id": book_id, "status": "error", "message": "Web検索結果が0件でした"}

    # background 生成
    print(f"  [{book_id}] background 生成中...")
    try:
        background = generate_background(title, author, snippets)
    except OllamaConnectionError:
        raise
    except Exception as e:
        return {"id": book_id, "status": "error", "message": f"background 生成失敗: {e}"}

    # 保存
    result = {
        "title":      title,
        "author":     author,
        "background": background,
    }
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  [{book_id}] → {out_path}")

    return {"id": book_id, "status": "ok", "message": "summary_web.json を作成しました"}


# ── メイン ───────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="SearXNG + Ollama で文学的背景を生成する")
    parser.add_argument("ids",        nargs="*",                         help="処理するID（省略時は全件）")
    parser.add_argument("--data-dir", default="backend/books_data",            help="dataディレクトリのパス")
    parser.add_argument("--force",    action="store_true",               help="既存の summary_web.json を上書き")
    parser.add_argument("--searxng",  default="http://localhost:8080",   help="SearXNG の URL")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"[error] データディレクトリが見つかりません: {data_dir}", file=sys.stderr)
        sys.exit(1)

    # 処理対象ディレクトリを決定
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

    print(f"対象: {len(book_dirs)} ディレクトリ / force={args.force} / searxng={args.searxng}")
    print("-" * 50)

    ok = skip = error = 0

    with ollama_ssh_tunnel():
        for book_dir in book_dirs:
            try:
                res = process_book(book_dir, args.searxng, args.force)
            except OllamaConnectionError as e:
                print(f"\n[fatal] {e}", file=sys.stderr)
                print(f"完了: ok={ok}  skip={skip}  error={error}  (接続切断により中断)", file=sys.stderr)
                sys.exit(1)

            status = res["status"].upper()
            print(f"[{status:5s}] {res['id']}: {res['message']}")

            if res["status"] == "ok":       ok    += 1
            elif res["status"] == "skip":   skip  += 1
            else:                           error += 1

    print("-" * 50)
    print(f"完了: ok={ok}  skip={skip}  error={error}")


if __name__ == "__main__":
    main()
