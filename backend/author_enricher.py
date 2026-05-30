"""
著者プロファイル生成スクリプト

Usage:
    python -m backend.author_enricher <author_id>
    python -m backend.author_enricher 6

出力先: backend/authors_data/{author_id}/profile.json
"""
import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

DB_FILE = "backend/aozora.db"
AUTHORS_DIR = Path("backend/authors_data")
MODEL = "claude-sonnet-4-6"
# MODEL="claude-haiku-4-5"


def get_author(author_id: int) -> dict | None:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, last_name, first_name, birth_year, death_year, nationality"
        " FROM authors WHERE id = ?",
        (author_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def full_name(author: dict) -> str:
    last = author.get("last_name") or ""
    first = author.get("first_name") or ""
    return (last + first).strip() or f"author_{author['id']}"


TOOLS = [
    {"type": "web_search_20250305", "name": "web_search"},
    {
        "name": "save_profile",
        "description": "調査した著者プロファイルを保存する",
        "input_schema": {
            "type": "object",
            "properties": {
                "literary_movements": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "文学運動・流派のリスト。なければ空リスト []",
                },
                "bio": {
                    "type": "string",
                    "description": "著者の紹介文（200〜300文字の日本語）。人物像・代表作・文学史上の意義を含む",
                },
            },
            "required": ["literary_movements", "bio"],
        },
    },
]


def enrich_author(author_id: int) -> dict:
    author = get_author(author_id)
    if not author:
        raise ValueError(f"Author {author_id} not found in DB")

    name = full_name(author)
    birth = author.get("birth_year")
    death = author.get("death_year")
    nationality = author.get("nationality") or "不明"

    death_str = f"{death}年" if death else "不明"
    prompt = f"""以下の著者について Web 検索で調査し、save_profile ツールで結果を記録してください。

著者名: {name}
生年: {birth}年
没年: {death_str}
国籍: {nationality}

収集する情報:
- literary_movements: 文学運動・流派（自然主義、白樺派、プロレタリア文学など）。なければ空リスト
- bio: 著者の紹介文（200〜300文字の日本語）。人物像・代表作・文学史上の意義を含む"""

    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": prompt}]
    profile_data = None

    for _ in range(10):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system="あなたは日本文学の専門家です。著者を調査し、必ず save_profile ツールで結果を保存してください。",
            tools=TOOLS,
            messages=messages,
        )

        tool_results = []
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                if block.name == "save_profile":
                    profile_data = block.input
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": "完了",
                })

        if profile_data:
            break

        if response.stop_reason == "end_turn":
            break

        if tool_results:
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

    if not profile_data:
        raise RuntimeError("save_profile が呼ばれませんでした。レスポンスを確認してください。")

    return {
        "author_id": author_id,
        "name": name,
        "birth_year": birth,
        "death_year": death,
        "literary_movements": profile_data.get("literary_movements", []),
        "bio": profile_data.get("bio", ""),
        "generated_at": datetime.now().isoformat(),
    }


def save_profile(author_id: int, profile: dict) -> Path:
    out_dir = AUTHORS_DIR / str(author_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "profile.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    return out_path


def main():
    parser = argparse.ArgumentParser(description="著者プロファイルを生成する")
    parser.add_argument("author_id", type=int, help="authors.id")
    args = parser.parse_args()

    print(f"[{args.author_id}] 調査中...")
    profile = enrich_author(args.author_id)
    path = save_profile(args.author_id, profile)
    print(f"保存: {path}")
    print(json.dumps(profile, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
