#!/usr/bin/env python3
"""
Brave Search API で作品情報を検索し、結果を data/{id}/brave_search.json に保存するスクリプト。

使用例:
  python -m backend.search_brave --id 1000
  python -m backend.search_brave --ids 1,2,3
  python -m backend.search_brave --limit 10 --offset 0
  python -m backend.search_brave --limit 20 --force
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

DB_FILE = "backend/aozora.db"
DATA_DIR = "backend/data"
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

MAX_CHARS_PER_PAGE = 3000
MAX_PAGES = 3

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "EbooksApp/1.0 (mofy100p@gmail.com)"})


def get_brave_api_key() -> str:
    key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not key:
        raise RuntimeError("BRAVE_SEARCH_API_KEY not found")
    return key


def brave_search(query: str, api_key: str, count: int = 5) -> list[dict]:
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    params = {"q": query, "count": count}
    resp = SESSION.get(BRAVE_SEARCH_URL, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data.get("web", {}).get("results", [])


def fetch_page_text(url: str, max_chars: int = MAX_CHARS_PER_PAGE) -> Optional[str]:
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


def gather_web_results(title: str, author: str, api_key: str) -> list[dict]:
    """
    Brave Search で作品情報を検索し、各ページ本文を収集して返す。

    Returns:
        [{"query": str, "url": str, "title": str, "description": str, "text": str | null}, ...]
    """
    queries = [
        f"{title} {author} 作品 解説 あらすじ",
        f"{title} {author} wikipedia",
    ]

    seen_urls: set[str] = set()
    results_out: list[dict] = []

    for query in queries:
        if len(results_out) >= MAX_PAGES:
            break
        try:
            results = brave_search(query, api_key, count=5)
        except Exception as e:
            print(f"    Brave Search エラー ({query}): {e}")
            continue

        for result in results:
            if len(results_out) >= MAX_PAGES:
                break
            url = result.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            text = fetch_page_text(url)
            if text and len(text) > 100:
                results_out.append({
                    "query": query,
                    "url": url,
                    "title": result.get("title", ""),
                    "description": result.get("description", ""),
                    "text": text,
                })
                print(f"    取得: {url}")

    return results_out


def process_book(
    brave_api_key: str,
    book_id: int,
    title: str,
    author: str,
    force: bool = False,
) -> bool:
    output_path = os.path.join(DATA_DIR, str(book_id), "brave_search.json")
    summary_path = os.path.join(DATA_DIR, str(book_id), "summary.json")

    if not force and os.path.exists(summary_path):
        print(f"  スキップ（既存）: [{book_id}] {title}")
        return True

    print(f"  処理中: [{book_id}] {title} / {author}", flush=True)

    try:
        web_results = gather_web_results(title, author, brave_api_key)
    except Exception as e:
        print(f"    エラー: {e}")
        return False

    if not web_results:
        print("    Web情報取得失敗")

    output = {
        "book_id": book_id,
        "title": title,
        "author": author,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "results": web_results,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"    保存: {output_path}")
    return True


def get_books(args) -> list[sqlite3.Row]:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if args.id:
        cursor.execute(
            "SELECT id, title, author FROM books WHERE id = ?",
            (args.id,),
        )
    elif args.ids:
        id_list = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
        placeholders = ",".join("?" * len(id_list))
        cursor.execute(
            f"SELECT id, title, author FROM books WHERE id IN ({placeholders}) ORDER BY id ASC",
            id_list,
        )
    else:
        cursor.execute(
            "SELECT id, title, author FROM books WHERE has_copyright = 0 ORDER BY id ASC LIMIT ? OFFSET ?",
            (100000, args.offset),
        )

    books = cursor.fetchall()
    conn.close()
    return books


def main() -> None:
    parser = argparse.ArgumentParser(description="Brave Search で作品情報を収集して保存")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--id", type=int, metavar="ID")
    target.add_argument("--ids", type=str, metavar="ID1,ID2,...")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--brave-api-key", type=str, metavar="KEY", help="Brave Search APIキー（省略時はBRAVE_SEARCH_API_KEY環境変数）")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    brave_api_key = args.brave_api_key or os.environ.get("BRAVE_SEARCH_API_KEY")
    if not brave_api_key:
        parser.error("BRAVE_SEARCH_API_KEY not found")

    books = get_books(args)
    if not books:
        print("対象作品が見つかりません")
        return

    success = 0
    count = 0
    for i, book in enumerate(books):
        if not args.force and os.path.exists(f"{DATA_DIR}/{book['id']}/summary.json"):
            print(f"  スキップ（既存）: [{book['id']}] {book['title']}")
            continue

        ok = process_book(
            brave_api_key,
            book_id=book["id"],
            title=book["title"],
            author=book["author"] or "",
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
