"""Trạng thái game và hoán vị nối ghép lưu trên server, để cookie chỉ giữ mã tham chiếu."""
import json
import secrets
import time
from typing import Any

from db import connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    student_name TEXT NOT NULL,
    token TEXT UNIQUE NOT NULL,
    started_at REAL NOT NULL,
    points INTEGER NOT NULL DEFAULT 0,
    streak INTEGER NOT NULL DEFAULT 0,
    finished INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS game_answers (
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL,
    given TEXT NOT NULL DEFAULT '',
    asked_at REAL,
    answered_at REAL,
    correct INTEGER,
    points INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (game_id, question_id)
);
CREATE TABLE IF NOT EXISTS match_maps (
    key TEXT PRIMARY KEY,
    mapping TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""


def init_schema() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


# ---------- hoán vị nối ghép ----------

def match_view(sid: str, question: dict[str, Any]) -> list[tuple[str, str]]:
    """Vế phải của một câu nối theo hoán vị riêng của phiên; trả về [(token, text)].
    Token ngẫu nhiên nên trình duyệt không suy ra thứ tự gốc."""
    key = f"{sid}:{question['id']}"
    pairs = question.get("options") or []
    with connect() as conn:
        row = conn.execute("SELECT mapping FROM match_maps WHERE key=?", (key,)).fetchone()
        if row:
            mapping = json.loads(row["mapping"])
        else:
            tokens = [secrets.token_hex(3) for _ in pairs]
            order = list(range(len(pairs)))
            secrets.SystemRandom().shuffle(order)
            mapping = {tokens[k]: order[k] for k in range(len(pairs))}
            conn.execute("INSERT INTO match_maps (key, mapping) VALUES (?,?)", (key, json.dumps(mapping)))
    ordered = sorted(mapping.items(), key=lambda kv: list(mapping.keys()).index(kv[0]))
    return [(tok, pairs[idx][1]) for tok, idx in ordered if idx < len(pairs)]


def match_decode(sid: str, question: dict[str, Any], given: str) -> str:
    """'0:ab12cd,1:ef34..' (token) -> '0:2,1:0' (chỉ số gốc) để chấm."""
    key = f"{sid}:{question['id']}"
    with connect() as conn:
        row = conn.execute("SELECT mapping FROM match_maps WHERE key=?", (key,)).fetchone()
    mapping = json.loads(row["mapping"]) if row else {}
    parts = []
    for part in (given or "").split(","):
        if ":" not in part:
            continue
        left, tok = part.split(":", 1)
        if tok in mapping and left.strip().isdigit():
            parts.append(f"{int(left)}:{mapping[tok]}")
    return ",".join(parts)


def decode_all(sid: str, quiz: dict[str, Any], given: dict[int, str]) -> dict[int, str]:
    """Giải mã mọi câu nối trong bài nộp."""
    out = dict(given)
    for q in quiz["questions"]:
        if q["qtype"] == "match":
            out[q["id"]] = match_decode(sid, q, given.get(q["id"], ""))
    return out


# ---------- ván game ----------

def start(quiz_id: int, student_name: str) -> str:
    """Tạo ván mới, trả về token để lưu trong cookie."""
    token = secrets.token_urlsafe(16)
    with connect() as conn:
        conn.execute(
            "INSERT INTO games (quiz_id, student_name, token, started_at) VALUES (?,?,?,?)",
            (quiz_id, student_name, token, time.time()),
        )
    return token


def get(token: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM games WHERE token=? AND finished=0", (token,)).fetchone()
    return dict(row) if row else None


def mark_asked(game_id: int, question_id: int) -> None:
    """Ghi thời điểm câu hỏi hiện ra (đồng hồ server), bỏ qua nếu đã ghi."""
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO game_answers (game_id, question_id, asked_at) VALUES (?,?,?)",
            (game_id, question_id, time.time()),
        )


def record_answer(game_id: int, question_id: int, given: str, correct: bool, points_fn) -> dict[str, Any] | None:
    """Ghi câu trả lời đúng một lần (có điều kiện trong SQL); trả None nếu câu đã trả lời.
    points_fn(elapsed, streak) -> điểm, với elapsed tính bằng đồng hồ server."""
    now = time.time()
    with connect() as conn:
        game = conn.execute("SELECT * FROM games WHERE id=? AND finished=0", (game_id,)).fetchone()
        if game is None:
            return None
        conn.execute(
            "INSERT OR IGNORE INTO game_answers (game_id, question_id, asked_at) VALUES (?,?,?)",
            (game_id, question_id, now),
        )
        row = conn.execute(
            "SELECT asked_at, answered_at FROM game_answers WHERE game_id=? AND question_id=?", (game_id, question_id)
        ).fetchone()
        if row["answered_at"] is not None:
            return None
        elapsed = max(0.0, now - float(row["asked_at"] or now))
        streak = game["streak"] + 1 if correct else 0
        pts = points_fn(elapsed, streak) if correct else 0
        updated = conn.execute(
            "UPDATE game_answers SET given=?, answered_at=?, correct=?, points=? WHERE game_id=? AND question_id=? AND answered_at IS NULL",
            (given, now, int(correct), pts, game_id, question_id),
        ).rowcount
        if not updated:
            return None
        conn.execute("UPDATE games SET points=points+?, streak=? WHERE id=?", (pts, streak, game_id))
        total = conn.execute("SELECT points FROM games WHERE id=?", (game_id,)).fetchone()["points"]
    return {"points": pts, "total": total, "streak": streak, "elapsed": elapsed}


def finish(token: str) -> dict[str, Any] | None:
    """Đóng ván (chỉ một lần) và trả về điểm, thời gian, câu trả lời."""
    with connect() as conn:
        game = conn.execute("SELECT * FROM games WHERE token=? AND finished=0", (token,)).fetchone()
        if game is None:
            return None
        conn.execute("UPDATE games SET finished=1 WHERE id=?", (game["id"],))
        answers = conn.execute("SELECT question_id, given FROM game_answers WHERE game_id=?", (game["id"],)).fetchall()
    return {
        "quiz_id": game["quiz_id"],
        "student_name": game["student_name"],
        "points": game["points"],
        "seconds": int(time.time() - game["started_at"]),
        "answers": {int(a["question_id"]): a["given"] or "" for a in answers},
    }
