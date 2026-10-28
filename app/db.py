"""Kết nối SQLite và khởi tạo lược đồ."""
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from config import DB_PATH, ensure_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    grade TEXT NOT NULL,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS quizzes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER REFERENCES materials(id),
    title TEXT NOT NULL,
    grade TEXT NOT NULL,
    code TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    source TEXT NOT NULL DEFAULT 'ai',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    qtype TEXT NOT NULL,
    prompt TEXT NOT NULL,
    options_json TEXT,
    answer TEXT NOT NULL,
    explanation TEXT NOT NULL DEFAULT '',
    topic TEXT NOT NULL DEFAULT '',
    image_path TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    student_name TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    plan_text TEXT NOT NULL DEFAULT '',
    game_points INTEGER,
    game_seconds INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    given TEXT NOT NULL,
    is_correct INTEGER NOT NULL,
    feedback TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS feedback (
    attempt_id INTEGER PRIMARY KEY REFERENCES attempts(id) ON DELETE CASCADE,
    rating INTEGER NOT NULL,
    comment TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    level INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""


TZ_FIX_KEY = "tz_fixed"
TZ_FIX_HOURS = 7  # bản ghi trước khi máy chủ đặt múi giờ Việt Nam được lưu theo UTC
TZ_FIX_BEFORE = "2026-10-27 09:00:00"  # mốc UTC lúc đặt múi giờ; bản ghi sau mốc đã đúng giờ VN
TIMESTAMP_TABLES = ("materials", "quizzes", "attempts", "hints", "feedback")


def init_db() -> None:
    """Tạo bảng nếu chưa tồn tại và chạy các sửa dữ liệu một lần."""
    ensure_dirs()
    with connect() as conn:
        conn.executescript(SCHEMA)
        from services.games import SCHEMA as GAME_SCHEMA

        conn.executescript(GAME_SCHEMA)
        _add_missing_columns(conn)
        _fix_utc_timestamps(conn)


NEW_COLUMNS = (
    ("questions", "image_path", "TEXT NOT NULL DEFAULT ''"),
    ("attempts", "game_points", "INTEGER"),
    ("attempts", "game_seconds", "INTEGER"),
)


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Thêm cột cho CSDL đã có từ trước (SQLite không có ADD COLUMN IF NOT EXISTS)."""
    for table, column, decl in NEW_COLUMNS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _fix_utc_timestamps(conn: sqlite3.Connection) -> None:
    """Dời +7 giờ cho mọi bản ghi tạo trước khi đặt múi giờ; chỉ chạy đúng một lần."""
    if conn.execute("SELECT 1 FROM meta WHERE key=?", (TZ_FIX_KEY,)).fetchone():
        return
    for table in TIMESTAMP_TABLES:
        conn.execute(
            f"UPDATE {table} SET created_at = datetime(created_at, '+{TZ_FIX_HOURS} hours') WHERE created_at < ?",
            (TZ_FIX_BEFORE,),
        )
    conn.execute("INSERT INTO meta (key, value) VALUES (?, datetime('now','localtime'))", (TZ_FIX_KEY,))


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Mở kết nối SQLite có row_factory và bật khóa ngoại."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
