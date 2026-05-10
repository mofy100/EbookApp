#!/usr/bin/env python3
"""
Claude Haiku で作品 summary.json を生成するスクリプト。

使用例:
  python -m backend.generate_summaries_claude --id 1000
  python -m backend.generate_summaries_claude --ids 1,2,3
  python -m backend.generate_summaries_claude --limit 10 --offset 0
  python -m backend.generate_summaries_claude --limit 20 --force
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone

import anthropic
from dotenv import load_dotenv

from backend.fetch_wikipedia import fetch_wikipedia

load_dotenv()

DB_FILE = "backend/aozora.db"
DATA_DIR = "backend/data"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """\
あなたは日本文学・世界文学の専門家です。
与えられた作品について百科事典レベルの正確性で作品情報JSONを生成してください。

【厳守事項】
- JSONのみ返す（markdown・コードブロック禁止）
- 推測禁止。不明な情報は null
- 日本語・敬体（です・ます調）で記述
- summary は 300〜500文字。ネタバレを避け、文学的特徴を含める
- tags は 5〜10個
- source_urls は空配列 [] を返すこと

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
  "themes": string[],
  "tags": string[],
  "awards": string[],
  "notable_points": str | null,
  "source_urls": []
}
"""


def create_client(api_key: str | None = None) -> anthropic.Anthropic:
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not found")
    return anthropic.Anthropic(api_key=key)


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
    wikipedia_text: str | None = None,
) -> dict:
    translator_line = f"\n翻訳者: {translator}" if translator else ""

    if wikipedia_text:
        prompt = (
            f"作品名: {title}\n著者: {author}{translator_line}\n\n"
            f"以下のWikipedia情報を参考に作品情報JSONを生成してください。\n\n---\n{wikipedia_text}\n---"
        )
        kwargs: dict = dict(
            model=CLAUDE_MODEL,
            max_tokens=1000,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
        )
    else:
        prompt = f"作品名: {title}\n著者: {author}{translator_line}\n\nこの作品について、Web検索を利用しながら作品情報JSONを生成してください。"
        kwargs = dict(
            model=CLAUDE_MODEL,
            max_tokens=1000,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
            tools=[{"type": "web_search_20260209", "name": "web_search", "allowed_callers": ["direct"]}],
        )

    response = client.messages.create(**kwargs)

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
        wiki = fetch_wikipedia(title, author)
        if wiki:
            print(f"    Wikipedia取得成功: {wiki['url']}")
            wikipedia_text = wiki.get("full_text") or wiki.get("summary", "")
            summary = call_claude(client, title, author, translator, wikipedia_text=wikipedia_text)
        else:
            print(f"    Wikipedia取得失敗 → web searchで生成")
            summary = call_claude(client, title, author, translator)
    except Exception as e:
        print(f"    エラー: {e}")
        return False

    summary["wiki_link"] = wiki["url"] if wiki else None
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


def add_wiki_links_to_existing(delay: float = 1.0) -> None:
    """既存の summary.json に wiki_link フィールドを追加する。"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    entries = []
    for book_dir in os.listdir(DATA_DIR):
        summary_path = os.path.join(DATA_DIR, book_dir, "summary.json")
        if os.path.exists(summary_path):
            entries.append((book_dir, summary_path))
    entries.sort(key=lambda x: int(x[0]) if x[0].isdigit() else 0)

    updated = skipped = 0
    for book_dir, summary_path in entries:
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)

        if "wiki_link" in summary:
            skipped += 1
            continue

        book_id = summary.get("book_id") or (int(book_dir) if book_dir.isdigit() else None)
        if book_id is None:
            continue

        cursor.execute("SELECT title, author FROM books WHERE id = ?", (book_id,))
        row = cursor.fetchone()
        if row is None:
            continue

        title, author = row["title"], row["author"] or ""
        print(f"  処理中: [{book_id}] {title} / {author}", flush=True)

        wiki = fetch_wikipedia(title, author)
        if wiki:
            summary["wiki_link"] = wiki["url"]
            print(f"    Wikipedia取得成功: {wiki['url']}")
        else:
            summary["wiki_link"] = None
            print("    Wikipedia取得失敗 → null を設定")

        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        updated += 1
        if delay > 0:
            time.sleep(delay)

    conn.close()
    print(f"\n完了: {updated} 件更新, {skipped} 件スキップ（既存）")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate summaries using Claude Haiku")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--id", type=int, metavar="ID")
    target.add_argument("--ids", type=str, metavar="ID1,ID2,...")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--api-key", type=str, metavar="KEY", help="Anthropic APIキー（省略時はANTHROPIC_API_KEY環境変数）")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--add-wiki-links", action="store_true", help="既存 summary.json に wiki_link を追加（Claude 不要）")
    args = parser.parse_args()

    if args.add_wiki_links:
        add_wiki_links_to_existing(delay=args.delay)
        return

    try:
        client = create_client(args.api_key)
    except RuntimeError as e:
        parser.error(str(e))

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
