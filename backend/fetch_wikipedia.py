#!/usr/bin/env python3
"""
作品タイトルと著者名から Wikipedia ページを取得するスクリプト。

使用例:
  python -m backend.fetch_wikipedia --title "坊っちゃん" --author "夏目漱石"
  python -m backend.fetch_wikipedia --title "吾輩は猫である" --author "夏目漱石" --lang en
  python -m backend.fetch_wikipedia --title "存在しない作品" --author "架空著者"
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

import requests

WIKIPEDIA_API = "https://{lang}.wikipedia.org/w/api.php"
WIKIPEDIA_URL = "https://{lang}.wikipedia.org/wiki/{title}"

DISAMBIGUATION_CATEGORIES = {"曖昧さ回避", "Disambiguation pages"}
WORK_CATEGORIES = {
    "小説", "戯曲", "詩", "随筆", "評論", "短編", "長編", "novel", "play", "poem",
    "short story", "essay", "novella",
}

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "EbooksApp/1.0 (mofy100p@gmail.com)"})


def _api(lang: str, **params) -> dict:
    params.setdefault("format", "json")
    params.setdefault("utf8", 1)
    url = WIKIPEDIA_API.format(lang=lang)
    resp = SESSION.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def search_wikipedia(query: str, lang: str, limit: int = 5) -> list[str]:
    """opensearch API でページタイトル候補を返す。"""
    data = _api(lang, action="opensearch", search=query, limit=limit, redirects="resolve")
    return data[1] if len(data) > 1 else []


def get_page(title: str, lang: str) -> Optional[dict]:
    """
    Action API でページの本文・要約・カテゴリを取得する。
    存在しない / リダイレクト失敗の場合は None を返す。
    """
    data = _api(
        lang,
        action="query",
        titles=title,
        prop="extracts|categories|info",
        exintro=True,          # 冒頭要約のみ (exintro)
        explaintext=True,      # プレーンテキスト
        inprop="url",
        cllimit=50,
        redirects=True,
    )
    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return None

    page = next(iter(pages.values()))
    if page.get("missing") is not None or page.get("id") == -1:
        return None

    categories = [
        c["title"].replace("Category:", "").replace("カテゴリ:", "")
        for c in page.get("categories", [])
    ]
    canonical_title = page.get("title", title)

    # 本文全体が必要な場合は別リクエスト
    full_data = _api(
        lang,
        action="query",
        titles=canonical_title,
        prop="extracts",
        explaintext=True,
        redirects=True,
    )
    full_pages = full_data.get("query", {}).get("pages", {})
    full_text = next(iter(full_pages.values())).get("extract", "") if full_pages else ""

    return {
        "title": canonical_title,
        "url": WIKIPEDIA_URL.format(lang=lang, title=canonical_title.replace(" ", "_")),
        "summary": page.get("extract", ""),
        "full_text": full_text,
        "categories": categories,
        "lang": lang,
    }


def _is_disambiguation(page: dict) -> bool:
    return any(
        cat in DISAMBIGUATION_CATEGORIES
        for cat in page["categories"]
    )


def _is_relevant(page: dict, title: str, author: str) -> bool:
    """ページが対象作品・著者に関連するか簡易判定する。"""
    page_title = page["title"].lower()
    title_lower = title.lower()
    author_lower = author.lower()

    # タイトルまたは著者名がページタイトルに含まれていれば関連あり
    if title_lower in page_title or author_lower in page_title:
        return True

    # カテゴリに著者名または作品ジャンルが含まれる場合も関連あり
    cats_lower = {c.lower() for c in page["categories"]}
    if author_lower in " ".join(cats_lower):
        return True
    if any(wc in cat for wc in WORK_CATEGORIES for cat in cats_lower):
        return True

    return False


def _try_fetch(query: str, lang: str, title: str, author: str) -> Optional[dict]:
    """クエリで検索し、最初に関連ありと判定されたページを返す。"""
    candidates = search_wikipedia(query, lang)
    for candidate in candidates:
        page = get_page(candidate, lang)
        if page is None:
            continue
        if _is_disambiguation(page):
            continue
        if _is_relevant(page, title, author):
            return page
    return None


def fetch_wikipedia(
    title: str,
    author: str,
    lang: str = "ja",
    fallback_lang: str = "en",
) -> Optional[dict]:
    """
    作品タイトルと著者名から Wikipedia ページを取得する。

    Args:
        title:        作品タイトル
        author:       著者名
        lang:         優先言語 (デフォルト: "ja")
        fallback_lang: フォールバック言語 (デフォルト: "en")。None で無効化。

    Returns:
        ページ情報の dict、または見つからない場合は None。
        {
            "title": str,       # Wikipedia 上のページタイトル
            "url": str,         # ページ URL
            "summary": str,     # 冒頭要約テキスト
            "full_text": str,   # 本文全体
            "categories": list, # カテゴリ一覧
            "lang": str,        # 取得言語
        }
    """
    for search_lang in filter(None, [lang, fallback_lang if fallback_lang != lang else None]):
        # 優先度1: タイトル + 著者
        result = _try_fetch(f"{title} {author}", search_lang, title, author)
        if result:
            return result

        # 優先度2: タイトルのみ
        result = _try_fetch(title, search_lang, title, author)
        if result:
            return result

    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Wikipedia ページ取得スクリプト")
    parser.add_argument("--title", required=True, help="作品タイトル")
    parser.add_argument("--author", required=True, help="著者名")
    parser.add_argument("--lang", default="ja", help="優先言語 (デフォルト: ja)")
    parser.add_argument("--no-fallback", action="store_true", help="英語フォールバックを無効化")
    parser.add_argument("--summary-only", action="store_true", help="冒頭要約のみ出力")
    args = parser.parse_args()

    fallback = None if args.no_fallback else ("en" if args.lang == "ja" else "ja")
    result = fetch_wikipedia(args.title, args.author, lang=args.lang, fallback_lang=fallback)

    if result is None:
        print(json.dumps(None, ensure_ascii=False))
        sys.exit(1)

    if args.summary_only:
        output = {k: result[k] for k in ("title", "url", "summary", "lang")}
    else:
        output = result

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
