import sqlite3
import os
import re
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from backend.parser import parse_aozora_html

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

os.makedirs("backend/data/gaiji", exist_ok=True)

def get_db_connection():
    # Rowオブジェクトとして取得することで辞書のようにアクセス可能にする
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/api/books")
def get_books(
    limit: int = 50, 
    offset: int = 0, 
    search: str = Query(None, description="タイトルか著者名での検索"),
    downloaded_only: bool = Query(False, description="ダウンロード済みの本のみ返すかどうか")
):
    """
    本の一覧を取得するAPI。検索やページネーションをサポート。
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT id, title, author, translator, card_url, text_url, is_downloaded, has_copyright FROM books WHERE has_copyright = 0"
    params = []
    
    if search:
        query += " AND (title LIKE ? OR author LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
        
    query += " ORDER BY id ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    # 全件数取得
    count_query = "SELECT COUNT(*) FROM books WHERE has_copyright = 0"
    count_params = []
    if search:
        count_query += " AND (title LIKE ? OR author LIKE ?)"
        count_params.extend([f"%{search}%", f"%{search}%"])
        
    cursor.execute(count_query, count_params)
    total_count = cursor.fetchone()[0]
    conn.close()
    
    books = []
    for r in rows:
        book_dict = dict(r)
        # ディレクトリが存在し中身があるかをチェックして真のダウンロード状態を判定
        book_dir = os.path.join(DATA_DIR, str(book_dict["id"]))
        is_downloaded_actual = os.path.exists(book_dir) and len(os.listdir(book_dir)) > 0
        book_dict["is_downloaded_actual"] = is_downloaded_actual
        
        # ダウンロード済みの本だけ返すモードの場合のスキップ処理
        if downloaded_only and not is_downloaded_actual:
            continue
            
        books.append(book_dict)
        
    return {
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "returned_count": len(books),
        "books": books
    }

@app.get("/api/books/{book_id}/text")
def get_book_text(book_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, author FROM books WHERE id = ?", (book_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Book not found in database")
        
    book_dir = os.path.join(DATA_DIR, str(book_id))
    if not os.path.exists(book_dir) or not os.listdir(book_dir):
        raise HTTPException(status_code=404, detail="Text data not downloaded yet. Please download first.")
        
    # ディレクトリ内のHTMLファイルを探す
    files = os.listdir(book_dir)
    html_files = [f for f in files if f.endswith('.html') or f.endswith('.htm')]
    
    if not html_files:
        raise HTTPException(status_code=404, detail="No readable HTML file found in the downloaded data")
        
    # 1. 開発モード（常に最新のパーサールールを適用）の判定
    AUTO_REPARSE = os.environ.get("AUTO_REPARSE", "").lower() == "true"
    
    # 2. 変換済みの content.html を探す (AUTO_REPARSEが無効な場合のみ再利用)
    content_path = os.path.join(book_dir, "content.html")
    
    # 互換性：まだ古い名前 (parsed.html) がある場合
    old_parsed_path = os.path.join(book_dir, "parsed.html")
    if not os.path.exists(content_path) and os.path.exists(old_parsed_path):
        os.rename(old_parsed_path, content_path)

    if os.path.exists(content_path) and not AUTO_REPARSE:
        target_file = "content.html"
        file_path = content_path
    else:
        # 3. ない場合（または開発モード）は origin.html からオンデマンドでパースする
        origin_path = os.path.join(book_dir, "origin.html")
        
        # 移行措置：どちらもない場合は既存のHTMLを探す
        if not os.path.exists(origin_path):
            html_files = [f for f in os.listdir(book_dir) if f.endswith('.html') or f.endswith('.htm')]
            html_files = [f for f in html_files if "content" not in f and "parsed" not in f]
            if html_files:
                os.rename(os.path.join(book_dir, html_files[0]), origin_path)
            else:
                raise HTTPException(status_code=404, detail="Original HTML (origin.html) not found")

        target_file = "content.html"
        file_path = os.path.join(book_dir, target_file)
        try:
            parse_aozora_html(origin_path, file_path)
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
        "id": row["id"],
        "title": row["title"],
        "author": row["author"],
        "filename": target_file,
        "content": content
    }

@app.get("/api/books/{book_id}/manifest")
def get_book_manifest(book_id: int):
    book_dir = os.path.join(DATA_DIR, str(book_id))
    manifest_path = os.path.join(book_dir, "manifest.json")
    
    if os.path.exists(manifest_path):
        import json
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    # マニフェストがない場合のフォールバック（単一ファイル構成として返す）
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT title, author FROM books WHERE id = ?", (book_id,))
    row = cursor.fetchone()
    conn.close()
    
    title = row["title"] if row else "Unknown"
    author = row["author"] if row else "Unknown"
    
    return {
        "title": title,
        "author": author,
        "chapter_count": 1,
        "chapters": [
            {
                "index": 0,
                "file": "content.html"
            }
        ]
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
    return FileResponse("frontend/index.html")

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
