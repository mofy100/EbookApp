#!/usr/bin/env python3
"""
Gemini を使って作品 summary.json を生成するスクリプト。

特徴:
- Gemini 2.5 Flash
- Google Search tool 使用
- Wikipedia以外のWeb情報も利用
- origin.html は参照しない
- backend/data/{id}/summary.json 保存
- DBから作品取得
- --id / --ids / --limit / --offset 対応

使用例:
  python -m backend.generate_summaries_gemini --id 1000

  python -m backend.generate_summaries_gemini --ids 1,2,3

  python -m backend.generate_summaries_gemini \
      --limit 10 \
      --offset 0

  python -m backend.generate_summaries_gemini \
      --limit 20 \
      --force

必要:
  pip install google-genai python-dotenv pydantic
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from google import genai

load_dotenv()

# =========================================================
# CONFIG
# =========================================================

DB_FILE = "backend/aozora.db"

DATA_DIR = "backend/data"

GEMINI_MODEL = "gemini-2.5-flash"


# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """\
あなたは日本文学・世界文学の専門家です。

与えられた作品について、
Web検索結果を活用し、
百科事典レベルの正確性で
作品情報JSONを生成してください。

【重要】
Wikipediaだけではなく、
以下のような情報源も積極的に参照してください。

- 出版社
- 文学館
- Britannica
- 青空文庫
- 書評
- 大学資料
- 国立国会図書館
- 新潮社
- 岩波書店
- 河出書房新社
- Project Gutenberg
- academic sources

【厳守事項】
- JSONのみ返す
- markdown禁止
- コードブロック禁止
- valid JSON を返す
- 推測禁止
- 不明な情報は null
- 日本語で記述
- summary は 300〜500文字
- ネタバレを避ける
- 文学的特徴を含める
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


# =========================================================
# GEMINI
# =========================================================

def create_client():

    api_key = os.environ.get(
        "GEMINI_API_KEY"
    )

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY not found"
        )

    return genai.Client(api_key=api_key)


# =========================================================
# CLEAN JSON
# =========================================================

def clean_json_text(raw: str) -> str:

    raw = raw.strip()

    # ```json ... ```

    if raw.startswith("```"):

        lines = raw.split("\n")

        # first line remove
        lines = lines[1:]

        # last ``` remove
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        raw = "\n".join(lines).strip()

    # 最初の { を探す
    start = raw.find("{")
    # 最後の } を探す
    end = raw.rfind("}")

    raw = raw[start:end + 1]

    return raw


# =========================================================
# GEMINI CALL
# =========================================================

def call_gemini(
    client,
    title: str,
    author: str,
    translator: str,
) -> dict:

    translator_line = ""

    if translator:

        translator_line = (
            f"\n翻訳者: {translator}\n"
        )

    prompt = f"""
作品名: {title}

著者: {author}
{translator_line}

この作品について、
Web検索を利用しながら、
作品情報JSONを生成してください。
"""

    response = client.models.generate_content(

        model=GEMINI_MODEL,

        contents=prompt,

        config={

            "system_instruction":
                SYSTEM_PROMPT,

            "tools": [
                {
                    "google_search": {}
                }
            ],

            "temperature": 0.1,
        },
    )

    if not response.text:

        raise RuntimeError(
            "Gemini returned empty response"
        )

    raw = clean_json_text(
        response.text
    )

    try:

        return json.loads(raw)

    except json.JSONDecodeError as e:

        print("\n=== RAW RESPONSE ===\n")
        print(raw)
        print("\n====================\n")

        raise RuntimeError(
            f"JSON parse error: {e}"
        )


# =========================================================
# PROCESS BOOK
# =========================================================

def process_book(
    client,
    book_id: int,
    title: str,
    author: str,
    translator: str,
    force: bool = False,
) -> bool:

    output_dir = os.path.join(
        DATA_DIR,
        str(book_id)
    )

    output_path = os.path.join(
        output_dir,
        "summary.json"
    )

    #
    # skip
    #

    if (
        not force
        and os.path.exists(output_path)
    ):

        print(
            f"  スキップ（既存）: "
            f"[{book_id}] {title}"
        )

        return True

    #
    # process
    #

    print(
        f"  処理中: "
        f"[{book_id}] {title} / {author}",
        flush=True,
    )

    try:

        summary = call_gemini(
            client,
            title,
            author,
            translator,
        )

    except Exception as e:

        print(f"    エラー: {e}")

        return False

    #
    # metadata
    #

    summary["book_id"] = book_id

    summary["generated_at"] = (
        datetime.now(timezone.utc)
        .isoformat()
    )

    #
    # save
    #

    os.makedirs(
        output_dir,
        exist_ok=True
    )

    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            summary,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(
        f"    保存: {output_path}"
    )

    return True


# =========================================================
# GET BOOKS
# =========================================================

def get_books(args):

    conn = sqlite3.connect(DB_FILE)

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    #
    # --id
    #

    if args.id:

        cursor.execute(
            """
            SELECT
                id,
                title,
                author,
                translator
            FROM books
            WHERE id = ?
            """,
            (args.id,),
        )

        books = cursor.fetchall()

    #
    # --ids
    #

    elif args.ids:

        id_list = [
            int(x.strip())
            for x in args.ids.split(",")
            if x.strip()
        ]

        placeholders = ",".join(
            "?" * len(id_list)
        )

        cursor.execute(
            f"""
            SELECT
                id,
                title,
                author,
                translator
            FROM books
            WHERE id IN ({placeholders})
            ORDER BY id ASC
            """,
            id_list,
        )

        books = cursor.fetchall()

    #
    # default
    #

    else:

        query = """
        SELECT
            id,
            title,
            author,
            translator
        FROM books
        WHERE has_copyright = 0
        ORDER BY id ASC
        LIMIT ?
        OFFSET ?
        """

        cursor.execute(
            query,
            (
                100000,
                args.offset,
            ),
        )

        books = cursor.fetchall()

    conn.close()

    return books


# =========================================================
# MAIN
# =========================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Generate summaries using Gemini"
        )
    )

    #
    # target
    #

    target = (
        parser.add_mutually_exclusive_group()
    )

    target.add_argument(
        "--id",
        type=int,
        metavar="ID",
    )

    target.add_argument(
        "--ids",
        type=str,
        metavar="ID1,ID2,...",
    )

    #
    # options
    #

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
    )

    parser.add_argument(
        "--offset",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--force",
        action="store_true",
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
    )

    args = parser.parse_args()

    #
    # client
    #

    client = create_client()

    #
    # books
    #

    books = get_books(args)

    if not books:

        print(
            "対象作品が見つかりません"
        )

        return

    success = 0
    count = 0

    for i, book in enumerate(books):

        # data/{id}/summary.jsonが存在していればスキップする
        if os.path.exists(f"{DATA_DIR}/{book['id']}/summary.json"):
            continue

        ok = process_book(
            client,
            book_id=book["id"],
            title=book["title"],
            author=book["author"] or "",
            translator=(
                book["translator"] or ""
            ),
            force=args.force,
        )

        if ok:
            success += 1
        
        count += 1
        if count == args.limit:
            break

        #
        # rate limit
        #

        if (
            args.delay > 0
            and i < len(books) - 1
        ):
            time.sleep(args.delay)

    print()

    print(
        f"完了: "
        f"{success}/{len(books)} 件成功"
    )


# =========================================================

if __name__ == "__main__":
    main()