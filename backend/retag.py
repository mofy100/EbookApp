#!/usr/bin/env python3
"""
既存 summary.json のタグをホワイトリストに基づき Batch API で一括再生成する。
Web検索は行わず、既存の summary テキストからタグを推定する。

使用例:
  python -m backend.retag
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

ALLOWED_TAGS_FILE = "backend/allowed_tags.json"
DATA_DIR = "backend/data"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

with open(ALLOWED_TAGS_FILE, encoding="utf-8") as f:
    allowed_data = json.load(f)

CATEGORIES = list(allowed_data["categories"].keys())

def _build_tag_list() -> str:
    lines = [
        f"【{cat}】" + " / ".join(tags)
        for cat, tags in allowed_data["categories"].items()
    ]
    notes = allowed_data.get("tag_notes", {})
    if notes:
        lines.append("\n【タグ使用上の注意】")
        for tag, note in notes.items():
            lines.append(f"- {tag}: {note}")
    return "\n".join(lines)

_TAG_LIST = _build_tag_list()

SYSTEM_PROMPT = f"""\
あなたは日本文学・世界文学の専門家です。
作品の情報（タイトル・著者・概要）を読み、以下のホワイトリストから適切なタグをカテゴリ別に選んでください。

【ルール】
- JSONのみ返す（markdown・コードブロック禁止）
- 全カテゴリのキーを必ず出力すること（該当なしは空配列 []）
- 合計3〜8個を目安に選ぶ
- リスト外のタグは絶対に使用しないこと

{_TAG_LIST}

出力形式:
{{
  "ジャンル": string[],
  "時代": string[],
  "文学運動・流派": string[],
  "テーマ": string[],
  "形式・文体": string[]
}}"""


def clean_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    s, e = text.find("{"), text.rfind("}")
    return text[s: e + 1] if s != -1 and e != -1 else text


def build_requests(files: list[Path]) -> tuple[list[dict], dict[str, Path]]:
    requests = []
    id_to_path: dict[str, Path] = {}

    for path in files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        book_id = str(data.get("book_id", ""))
        title = data.get("title") or ""
        author = data.get("author") or ""
        translator = data.get("translator") or ""
        summary = data.get("summary") or ""

        if not summary:
            print(f"  スキップ（summary なし）: [{book_id}] {title}")
            continue

        translator_line = f"翻訳者: {translator}\n" if translator else ""
        user_prompt = f"作品名: {title}\n著者: {author}\n{translator_line}概要: {summary}"

        requests.append({
            "custom_id": book_id,
            "params": {
                "model": CLAUDE_MODEL,
                "max_tokens": 400,
                "system": [
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                "messages": [{"role": "user", "content": user_prompt}],
            },
        })
        id_to_path[book_id] = path

    return requests, id_to_path


def submit_and_wait(client: anthropic.Anthropic, requests: list[dict]) -> str:
    batch = client.messages.batches.create(requests=requests)
    batch_id = batch.id
    print(f"バッチ送信完了: {len(requests)} 件  ID={batch_id}")

    while True:
        batch = client.messages.batches.retrieve(batch_id)
        counts = batch.request_counts
        print(
            f"  処理中... succeeded={counts.succeeded} "
            f"errored={counts.errored} "
            f"processing={counts.processing}"
        )
        if batch.processing_status == "ended":
            break
        time.sleep(20)

    return batch_id


def apply_results(
    client: anthropic.Anthropic,
    batch_id: str,
    id_to_path: dict[str, Path],
) -> tuple[int, int]:
    success = errors = 0

    for result in client.messages.batches.results(batch_id):
        custom_id = result.custom_id
        path = id_to_path.get(custom_id)
        if not path:
            continue

        if result.result.type != "succeeded":
            print(f"  FAILED [{custom_id}]: {result.result.type}")
            errors += 1
            continue

        try:
            raw = result.result.message.content[0].text
            new_tags = json.loads(clean_json(raw))

            for cat in CATEGORIES:
                if cat not in new_tags:
                    new_tags[cat] = []

            # ホワイトリスト外タグを除去
            allowed_set = {
                t for ts in allowed_data["categories"].values() for t in ts
            }
            for cat in CATEGORIES:
                new_tags[cat] = [t for t in new_tags[cat] if t in allowed_set]

            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data["tags"] = new_tags
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            tag_n = sum(len(v) for v in new_tags.values())
            title = data.get("title", "")
            print(f"  [{custom_id}] {title}  → {tag_n}タグ")
            success += 1

        except Exception as e:
            print(f"  PARSE ERROR [{custom_id}]: {e}")
            errors += 1

    return success, errors


def main() -> None:
    client = anthropic.Anthropic()

    files = sorted(Path(DATA_DIR).glob("*/summary.json"))
    print(f"対象ファイル: {len(files)} 件")

    requests, id_to_path = build_requests(files)
    if not requests:
        print("処理対象なし")
        return

    batch_id = submit_and_wait(client, requests)
    success, errors = apply_results(client, batch_id, id_to_path)

    print(f"\n完了: {success} 件成功 / {errors} 件エラー")


if __name__ == "__main__":
    main()
