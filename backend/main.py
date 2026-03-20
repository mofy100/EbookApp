from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import sqlite3
import os

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
    
    query = "SELECT id, title, author, translator, card_url, text_url, is_downloaded, has_copyright FROM books WHERE 1=1"
    params = []
    
    if search:
        query += " AND (title LIKE ? OR author LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
        
    query += " ORDER BY id ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    # 全件数取得
    count_query = "SELECT COUNT(*) FROM books WHERE 1=1"
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
    """
    指定したbook_idのテキスト内容を取得して返すAPI。
    あらかじめ backend/data/{book_id}/ 配下にダウンロード・解凍されている必要がある。
    """
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
        
    # ディレクトリ内のテキストファイルを探す
    files = os.listdir(book_dir)
    text_files = [f for f in files if f.endswith('.txt') or f.endswith('.html')]
    
    if not text_files:
        raise HTTPException(status_code=404, detail="No readable text file found in the downloaded data")
        
    # 通常1つのはずなので最初のものを開く
    target_file = text_files[0]
    file_path = os.path.join(book_dir, target_file)
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")
        
    return {
        "id": row["id"],
        "title": row["title"],
        "author": row["author"],
        "filename": target_file,
        "content": content
    }

# -------- フロントエンドの静的ファイル配信 --------
# ※ APIルート( /api/* ) 以外のアクセスはすべて frontend/ 以下のファイルを返す
@app.get("/")
def read_root():
    return FileResponse("frontend/index.html")

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
