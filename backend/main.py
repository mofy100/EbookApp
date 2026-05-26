import sqlite3
import os
import re
import json
from typing import List
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from backend.builder import process_aozora

app = FastAPI(title="Aozora Bunko API")

# CORS設定 (Next.jsフロントエンドプロセスからの呼び出しを許可)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # 開発用のため全許可
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = "backend/aozora.db"
DATA_DIR = "backend/data"
TAGS_JSON_PATH = "backend/tags.json"

# FORCE_REPARSE=1 を設定した場合、manifest が存在しても毎回再パースする
FORCE_REPARSE = os.environ.get("FORCE_REPARSE", "0") == "1"

os.makedirs("backend/data/gaiji", exist_ok=True)

# タグのカテゴリマップ・順序マップ（tags.json から構築）
def _build_tag_maps() -> tuple[dict, dict]:
    if not os.path.exists(TAGS_JSON_PATH):
        return {}, {}
    with open(TAGS_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    category_map = {}
    order_map = {}
    for cat, tags in data.get("categories", {}).items():
        for i, tag in enumerate(tags):
            category_map[tag] = cat
            order_map[tag] = i
    return category_map, order_map

_TAG_CATEGORY_MAP, _TAG_ORDER_MAP = _build_tag_maps()


def sync_book_tags():
    """既存の summary_qwen.json を走査して book_tags テーブルを再構築する"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM book_tags")

    inserted = 0
    if not os.path.exists(DATA_DIR):
        conn.commit()
        conn.close()
        return

    for dir_name in os.listdir(DATA_DIR):
        try:
            book_id = int(dir_name)
        except ValueError:
            continue
        json_path = os.path.join(DATA_DIR, dir_name, "summary_qwen.json")
        if not os.path.exists(json_path):
            continue
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
        except Exception:
            continue
        tags_obj = summary.get("overall", {}).get("tags", {})
        if isinstance(tags_obj, dict):
            tag_list = [t for vals in tags_obj.values() for t in vals if t]
        elif isinstance(tags_obj, list):
            tag_list = [t for t in tags_obj if t]
        else:
            tag_list = []
        for tag in tag_list:
            cursor.execute(
                "INSERT OR IGNORE INTO book_tags (book_id, tag) VALUES (?, ?)",
                (book_id, tag)
            )
            inserted += 1

    conn.commit()
    conn.close()
    print(f"[INFO] sync_book_tags: {inserted} entries synced")


def ensure_book_tags():
    """起動時に book_tags テーブルを作成し、必要なら同期する"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS book_tags (
            book_id INTEGER NOT NULL,
            tag     TEXT    NOT NULL,
            PRIMARY KEY (book_id, tag),
            FOREIGN KEY (book_id) REFERENCES books(book_id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_book_tags_tag ON book_tags(tag)")
    conn.commit()

    # summary ファイル数と登録済み book 数が一致しない場合に同期
    summary_count = sum(
        1 for d in os.listdir(DATA_DIR)
        if os.path.exists(os.path.join(DATA_DIR, d, "summary_qwen.json"))
    ) if os.path.exists(DATA_DIR) else 0
    cursor.execute("SELECT COUNT(DISTINCT book_id) FROM book_tags")
    tagged_count = cursor.fetchone()[0]
    conn.close()

    if summary_count != tagged_count:
        print(f"[INFO] book_tags: {tagged_count} tagged / {summary_count} summaries — syncing")
        sync_book_tags()


def load_summary(book_id: int) -> dict:
    path = os.path.join(DATA_DIR, str(book_id), "summary_qwen.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] load_summary: failed to parse {path}: {e}")
    return {}

def get_db_connection():
    # Rowオブジェクトとして取得することで辞書のようにアクセス可能にする
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


ensure_book_tags()


@app.get("/api/tags")
def get_tags():
    """利用可能なタグ一覧をカテゴリ・件数付きで返す"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT tag, COUNT(*) as count FROM book_tags GROUP BY tag ORDER BY count DESC, tag ASC"
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "tag": r["tag"],
            "count": r["count"],
            "category": _TAG_CATEGORY_MAP.get(r["tag"], ""),
            "order": _TAG_ORDER_MAP.get(r["tag"], 9999),
        }
        for r in rows
    ]


@app.post("/api/admin/sync-tags")
def admin_sync_tags():
    """summary_qwen.json から book_tags を手動で再同期する"""
    sync_book_tags()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM book_tags")
    count = cursor.fetchone()[0]
    conn.close()
    return {"status": "ok", "entries": count}


@app.get("/api/books")
def get_books(
    limit: int = 50,
    offset: int = 0,
    search: str = Query(None, description="タイトルか著者名での検索"),
    downloaded_only: bool = Query(False, description="ダウンロード済みの本のみ返すかどうか"),
    tags: List[str] = Query(default=[], description="タグによるAND絞り込み"),
):
    """
    本の一覧を取得するAPI。検索・タグ絞り込み・ページネーションをサポート。
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT book_id, title, author, translator, publication_year FROM books WHERE 1=1"
    params = []

    if search:
        query += " AND (title LIKE ? OR author LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])

    for i, tag in enumerate(tags):
        query += f" AND EXISTS (SELECT 1 FROM book_tags bt{i} WHERE bt{i}.book_id = books.book_id AND bt{i}.tag = ?)"
        params.append(tag)

    query += " ORDER BY book_id ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor.execute(query, params)
    rows = cursor.fetchall()

    # 全件数取得
    count_query = "SELECT COUNT(*) FROM books WHERE 1=1"
    count_params = []
    if search:
        count_query += " AND (title LIKE ? OR author LIKE ?)"
        count_params.extend([f"%{search}%", f"%{search}%"])
    for i, tag in enumerate(tags):
        count_query += f" AND EXISTS (SELECT 1 FROM book_tags bt{i} WHERE bt{i}.book_id = books.book_id AND bt{i}.tag = ?)"
        count_params.append(tag)

    cursor.execute(count_query, count_params)
    total_count = cursor.fetchone()[0]
    conn.close()
    
    books = []
    for r in rows:
        book_dict = dict(r)
        book_dir = os.path.join(DATA_DIR, str(book_dict["book_id"]))
        is_downloaded_actual = os.path.exists(book_dir) and len(os.listdir(book_dir)) > 0
        book_dict["is_downloaded_actual"] = is_downloaded_actual

        if downloaded_only and not is_downloaded_actual:
            continue

        summary = load_summary(book_dict["book_id"])
        book_dict["tags"] = summary.get("overall", {}).get("tags", [])
        book_dict["summary"] = summary.get("overall", {}).get("summary") or None

        books.append(book_dict)

    return {
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "returned_count": len(books),
        "books": books
    }

@app.get("/api/books/{book_id}/summary")
def get_book_summary(book_id: int):
    """summary.json の内容を返す。存在しない場合は空オブジェクトを返す。"""
    return load_summary(book_id)


@app.get("/api/books/{book_id}/text")
def get_book_text(book_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT book_id, title, author FROM books WHERE book_id = ?", (book_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Book not found in database")
        
    book_dir = os.path.join(DATA_DIR, str(book_id))
    if not os.path.exists(book_dir) or not os.listdir(book_dir):
        raise HTTPException(status_code=404, detail="Text data not downloaded yet. Please download first.")
        
    origin_path = os.path.join(book_dir, "origin.html")
    if not os.path.exists(origin_path):
        raise HTTPException(status_code=404, detail="Original HTML (origin.html) not found")

    target_file = "content_0.html"
    file_path = os.path.join(book_dir, target_file)
    try:
        process_aozora(origin_path, book_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse file: {str(e)}")
            
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")
        
    # E-book DOM形式になっているため、動的な正規表現置換は全て不要になりました
    # 全角スペースの詰まりなどは parser 側で処理済、あるいはCSSの字下げで処理されます
        
    return {
        "id": row["book_id"],
        "title": row["title"],
        "author": row["author"],
        "filename": target_file,
        "content": content
    }

@app.get("/api/books/{book_id}/manifest")
def get_book_manifest(book_id: int):
    import json
    book_dir = os.path.join(DATA_DIR, str(book_id))
    origin_path = os.path.join(book_dir, "origin.html")

    manifest_path = os.path.join(book_dir, "manifest.json")

    if os.path.exists(origin_path) and (FORCE_REPARSE or not os.path.exists(manifest_path)):
        try:
            process_aozora(origin_path, book_dir)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to parse file: {str(e)}")
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # origin.html もマニフェストもない場合のフォールバック
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT title, author FROM books WHERE book_id = ?", (book_id,))
    row = cursor.fetchone()
    conn.close()

    title = row["title"] if row else "Unknown"
    author = row["author"] if row else "Unknown"

    return {
        "title": title,
        "author": author,
        "chapter_count": 1,
        "chapters": [{"index": 0, "file": "content.html"}]
    }

@app.get("/api/books/{book_id}/chunk/{filename}")
def get_book_chunk(book_id: int, filename: str):
    # セキュリティチェック：ファイル名が不正なパスを含まないか
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
        
    book_dir = os.path.join(DATA_DIR, str(book_id))
    file_path = os.path.join(book_dir, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Chunk file not found")
        
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read chunk: {str(e)}")

# -------- 静的ファイルと画像の配信 --------
app.mount("/api/assets/gaiji", StaticFiles(directory="backend/data/gaiji"), name="gaiji")

@app.get("/")
def read_root():
    return FileResponse("frontend/ebook-launch.html")

@app.get("/app")
def read_app():
    return FileResponse("frontend/index.html")

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
