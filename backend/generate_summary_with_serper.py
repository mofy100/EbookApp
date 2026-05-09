#!/usr/bin/env python3
"""
Serper API + Claude Haiku で作品 summary.json を生成するスクリプト。

使用例:
  python -m backend.generate_summary_with_serper --id 1000
  python -m backend.generate_summary_with_serper --ids 1,2,3
  python -m backend.generate_summary_with_serper --limit 10 --offset 0
  python -m backend.generate_summary_with_serper --limit 20 --force
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional

import anthropic
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

DB_FILE = "backend/aozora.db"
DATA_DIR = "backend/data"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
SERPER_SEARCH_URL = "https://google.serper.dev/search"

MAX_CHARS_PER_PAGE = 3000
MAX_PAGES = 3

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "EbooksApp/1.0 (mofy100p@gmail.com)"})

SYSTEM_PROMPT = """\
あなたは日本文学・世界文学の専門家です。
与えられた作品について百科事典レベルの正確性で作品情報JSONを生成してください。

【厳守事項】
- JSONのみ返す（markdown・コードブロック禁止）
- 推測禁止。不明な情報は null
- 日本語・敬体（です・ます調）で記述
- summary は 300〜500文字。ネタバレを避け、文学的特徴を含める
- tags は 5個前後。作品のジャンルやテーマなどを考慮すること

JSON schema:
{
  "title": str,
  "original_title": str | null,
  "author": str,
  "translator": str | null,
  "country": str | null,
  "genre": str | null,
  "subgenre": string[],
  "publication_year": int | null,
  "japanese_publication_year": int | null,
  "summary": str,
  "tags": string[],
  "source_urls": string[],
}
"""


def create_claude_client(api_key: str | None = None) -> anthropic.Anthropic:
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not found")
    return anthropic.Anthropic(api_key=key)


def get_serper_api_key() -> str:
    key = os.environ.get("SERPER_API_KEY")
    if not key:
        raise RuntimeError("SERPER_API_KEY not found")
    return key


def serper_search(query: str, api_key: str, num: int = 5) -> list[dict]:
    """Serper API で検索し、結果のリストを返す。"""
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload = {"q": query, "num": num, "gl": "jp", "hl": "ja"}
    resp = SESSION.post(SERPER_SEARCH_URL, headers=headers, json=payload, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data.get("organic", [])


def fetch_page_text(url: str, max_chars: int = MAX_CHARS_PER_PAGE) -> Optional[str]:
    """URLのページ本文をテキストで取得する。失敗時は None を返す。"""
    try:
        resp = SESSION.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text[:max_chars]
    except Exception:
        return None


def gather_web_context(title: str, author: str, api_key: str) -> tuple[str, list[str]]:
    """
    Serper で作品情報を検索し、ページ本文を収集する。

    Returns:
        (収集テキストを結合した文字列, 参照したURLリスト)
    """
    queries = [
        f"{title} {author} 作品 解説 あらすじ",
        f"{title} {author} wikipedia",
    ]

    seen_urls: set[str] = set()
    collected: list[tuple[str, str]] = []  # (url, text)

    for query in queries:
        if len(collected) >= MAX_PAGES:
            break
        try:
            results = serper_search(query, api_key, num=5)
        except Exception as e:
            print(f"    Serper Search エラー ({query}): {e}")
            continue

        for result in results:
            if len(collected) >= MAX_PAGES:
                break
            url = result.get("link", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            text = fetch_page_text(url)
            if text and len(text) > 100:
                collected.append((url, text))
                print(f"    取得: {url}")

    if not collected:
        return "", []

    parts = []
    for i, (url, text) in enumerate(collected, 1):
        parts.append(f"--- 参考ページ {i}: {url} ---\n{text}")

    return "\n\n".join(parts), [url for url, _ in collected]


def clean_json_text(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        return raw
    return raw[start:end + 1]


def call_claude(
    client: anthropic.Anthropic,
    title: str,
    author: str,
    translator: str,
    web_context: str,
) -> dict:
    translator_line = f"\n翻訳者: {translator}" if translator else ""

    if web_context:
        prompt = (
            f"作品名: {title}\n著者: {author}{translator_line}\n\n"
            f"以下のWeb情報を参考に作品情報JSONを生成してください。\n\n{web_context}"
        )
        system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
    else:
        prompt = (
            f"作品名: {title}\n著者: {author}{translator_line}\n\n"
            f"この作品について作品情報JSONを生成してください。"
        )
        system = SYSTEM_PROMPT

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )

    text = next((b.text for b in reversed(response.content) if b.type == "text"), "")
    if not text:
        raise RuntimeError("Claude returned empty response")

    raw = clean_json_text(text)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"\n=== RAW RESPONSE ===\n{raw}\n====================\n")
        raise RuntimeError(f"JSON parse error: {e}")


def process_book(
    client: anthropic.Anthropic,
    serper_api_key: str,
    book_id: int,
    title: str,
    author: str,
    translator: str,
    force: bool = False,
) -> bool:
    output_path = os.path.join(DATA_DIR, str(book_id), "summary.json")

    if not force and os.path.exists(output_path):
        print(f"  スキップ（既存）: [{book_id}] {title}")
        return True

    print(f"  処理中: [{book_id}] {title} / {author}", flush=True)

    try:
        web_context, source_urls = gather_web_context(title, author, serper_api_key)
        if not web_context:
            print("    Web情報取得失敗 → 知識のみで生成")

        summary = call_claude(client, title, author, translator, web_context)
    except Exception as e:
        print(f"    エラー: {e}")
        return False

    if source_urls and not summary.get("source_urls"):
        summary["source_urls"] = source_urls

    summary["book_id"] = book_id
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"    保存: {output_path}")
    return True


def get_books(args) -> list[sqlite3.Row]:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if args.id:
        cursor.execute(
            "SELECT id, title, author, translator FROM books WHERE id = ?",
            (args.id,),
        )
    elif args.ids:
        id_list = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
        placeholders = ",".join("?" * len(id_list))
        cursor.execute(
            f"SELECT id, title, author, translator FROM books WHERE id IN ({placeholders}) ORDER BY id ASC",
            id_list,
        )
    else:
        cursor.execute(
            "SELECT id, title, author, translator FROM books WHERE has_copyright = 0 ORDER BY id ASC LIMIT ? OFFSET ?",
            (100000, args.offset),
        )

    books = cursor.fetchall()
    conn.close()
    return books


def main() -> None:
    parser = argparse.ArgumentParser(description="Serper Search + Claude Haiku でサマリーを生成")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--id", type=int, metavar="ID")
    target.add_argument("--ids", type=str, metavar="ID1,ID2,...")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--api-key", type=str, metavar="KEY", help="Anthropic APIキー（省略時はANTHROPIC_API_KEY環境変数）")
    parser.add_argument("--serper-api-key", type=str, metavar="KEY", help="Serper APIキー（省略時はSERPER_API_KEY環境変数）")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    try:
        client = create_claude_client(args.api_key)
    except RuntimeError as e:
        parser.error(str(e))

    serper_api_key = args.serper_api_key or os.environ.get("SERPER_API_KEY")
    if not serper_api_key:
        parser.error("SERPER_API_KEY not found")

    books = get_books(args)
    if not books:
        print("対象作品が見つかりません")
        return

    success = 0
    count = 0
    for i, book in enumerate(books):
        if not args.force and os.path.exists(f"{DATA_DIR}/{book['id']}/summary.json"):
            continue

        ok = process_book(
            client,
            serper_api_key,
            book_id=book["id"],
            title=book["title"],
            author=book["author"] or "",
            translator=book["translator"] or "",
            force=args.force,
        )
        if ok:
            success += 1

        count += 1
        if count == args.limit:
            break

        if args.delay > 0 and i < len(books) - 1:
            time.sleep(args.delay)

    print(f"\n完了: {success}/{count} 件成功")


if __name__ == "__main__":
    main()
