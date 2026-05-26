import os
import sqlite3
from fastapi import APIRouter, HTTPException, Header, Query
from pydantic import BaseModel

router = APIRouter()

DB_FILE = "backend/aozora.db"
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")


def _get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_posts_table():
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL,
            message    TEXT    NOT NULL,
            user_id    INTEGER,
            is_hidden  BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.commit()
    conn.close()


class PostCreate(BaseModel):
    name: str
    message: str
    is_hidden: bool = False


class PostResponse(BaseModel):
    id: int
    name: str
    message: str
    created_at: str


@router.get("/api/posts", response_model=list[PostResponse])
def list_posts(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, name, message, created_at FROM posts"
        " WHERE is_hidden = FALSE ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/posts", response_model=PostResponse, status_code=201)
def create_post(body: PostCreate):
    name = body.name.strip()
    message = body.message.strip()
    if not name or not message:
        raise HTTPException(status_code=422, detail="名前とメッセージは必須です")
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO posts (name, message, is_hidden) VALUES (?, ?, ?)",
        (name, message, body.is_hidden),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, name, message, created_at FROM posts WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()
    conn.close()
    return dict(row)


@router.delete("/api/posts/{post_id}", status_code=204)
def delete_post(post_id: int, x_admin_key: str = Header(...)):
    if not ADMIN_KEY or x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")
    conn = _get_conn()
    conn.execute("UPDATE posts SET is_hidden = TRUE WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()
