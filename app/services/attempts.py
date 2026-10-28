"""Lượt làm bài của học sinh: chấm, lưu, thống kê."""
import re
import threading
from collections import Counter
from typing import Any

from ai.batch import grade_and_plan
from ai.tutor import make_hint
from config import MAX_HINTS_PER_QUESTION
from db import connect


RESUBMIT_WINDOW_SECONDS = 20
_submit_locks: dict[tuple[int, str], threading.Lock] = {}
_submit_locks_guard = threading.Lock()


def _lock_for(quiz_id: int, name: str) -> threading.Lock:
    with _submit_locks_guard:
        return _submit_locks.setdefault((quiz_id, name.strip().lower()), threading.Lock())


def _recent_attempt(quiz_id: int, name: str) -> int | None:
    """Lượt làm của cùng em trong vài giây gần nhất (bấm đúp, mạng chậm)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM attempts WHERE quiz_id=? AND lower(trim(student_name))=lower(trim(?))"
            " AND created_at >= datetime('now','localtime', ?) ORDER BY id DESC LIMIT 1",
            (quiz_id, name, f"-{RESUBMIT_WINDOW_SECONDS} seconds"),
        ).fetchone()
    return int(row["id"]) if row else None


def submit_attempt(quiz: dict[str, Any], student_name: str, given: dict[int, str]) -> int:
    """Chấm và lưu lượt làm; cùng em nộp lại trong 20 giây thì trả lượt đã có thay vì tạo thêm."""
    with _lock_for(quiz["id"], student_name):
        existing = _recent_attempt(quiz["id"], student_name)
        if existing is not None:
            return existing
        return _create_attempt(quiz, student_name, given)


def create_game_attempt(quiz: dict[str, Any], student_name: str, given: dict[int, str]) -> int:
    """Lượt chơi game: luôn là lượt mới, chấm ngoại tuyến để không tốn hạn mức AI cho mỗi ván."""
    with _lock_for(quiz["id"], student_name):
        return _create_attempt(quiz, student_name, given, use_ai=False)


def _create_attempt(quiz: dict[str, Any], student_name: str, given: dict[int, str], use_ai: bool = True) -> int:
    graded, plan = grade_and_plan(quiz, student_name, given, use_ai=use_ai)
    score = sum(1 for _, _, ok, _ in graded if ok)
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO attempts (quiz_id, student_name, score, total, plan_text) VALUES (?,?,?,?,?)",
            (quiz["id"], student_name.strip(), score, len(graded), plan),
        )
        attempt_id = int(cur.lastrowid)
        conn.executemany(
            "INSERT INTO answers (attempt_id, question_id, given, is_correct, feedback) VALUES (?,?,?,?,?)",
            [(attempt_id, q["id"], g, int(ok), fb) for q, g, ok, fb in graded],
        )
    return attempt_id


def _unique(items: list[str]) -> list[str]:
    seen: list[str] = []
    for it in items:
        if it not in seen:
            seen.append(it)
    return seen


def get_attempt(attempt_id: int) -> dict[str, Any] | None:
    """Lượt làm kèm từng câu, câu hỏi và gợi ý đã nhận."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        if not row:
            return None
        answers = conn.execute(
            "SELECT a.*, q.prompt, q.qtype, q.options_json, q.answer, q.explanation, q.topic, q.position"
            " FROM answers a JOIN questions q ON q.id=a.question_id WHERE a.attempt_id=? ORDER BY q.position",
            (attempt_id,),
        ).fetchall()
        hints = conn.execute(
            "SELECT question_id, level, text FROM hints WHERE attempt_id=? ORDER BY level", (attempt_id,)
        ).fetchall()
        quiz = conn.execute("SELECT * FROM quizzes WHERE id=?", (row["quiz_id"],)).fetchone()
    import json

    hint_map: dict[int, list[dict[str, Any]]] = {}
    for h in hints:
        hint_map.setdefault(h["question_id"], []).append(dict(h))
    result = dict(row)
    result["quiz"] = dict(quiz)
    result["answers"] = []
    for a in answers:
        item = dict(a)
        item["options"] = json.loads(item.pop("options_json") or "[]")
        item["hints"] = hint_map.get(a["question_id"], [])
        result["answers"].append(item)
    return result


def request_hint(attempt_id: int, question_id: int) -> dict[str, Any]:
    """Gợi ý mức tiếp theo cho một câu sai; sau mức cuối trả thêm đáp án và giải thích để em đối chiếu."""
    text, item = _next_hint(attempt_id, question_id)
    reveal = len(item["hints"]) + 1 >= MAX_HINTS_PER_QUESTION
    result: dict[str, Any] = {"hint": text}
    if reveal:
        result["answer"] = item["answer"]
        result["explanation"] = item["explanation"]
    return result


def _next_hint(attempt_id: int, question_id: int) -> tuple[str, dict[str, Any]]:
    """Tạo (hoặc lặp lại) gợi ý và trả về cả bản ghi câu trả lời."""
    attempt = get_attempt(attempt_id)
    if attempt is None:
        raise LookupError("Không tìm thấy lượt làm")
    item = next((a for a in attempt["answers"] if a["question_id"] == question_id), None)
    if item is None:
        raise LookupError("Không tìm thấy câu hỏi")
    if item["is_correct"]:
        return "Câu này em đã làm đúng rồi, không cần gợi ý nữa!", item
    level = len(item["hints"]) + 1
    if level > MAX_HINTS_PER_QUESTION:
        return item["hints"][-1]["text"], item
    text = make_hint(item, item["given"], level, attempt["quiz"]["grade"])
    with connect() as conn:
        conn.execute(
            "INSERT INTO hints (attempt_id, question_id, level, text) VALUES (?,?,?,?)",
            (attempt_id, question_id, level, text),
        )
    return text, item


RATING_LABEL = {3: "Thích", 2: "Bình thường", 1: "Thấy khó"}


def save_feedback(attempt_id: int, rating: int, comment: str) -> None:
    """Lưu hoặc cập nhật nhận xét của học sinh cho một lượt làm."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO feedback (attempt_id, rating, comment) VALUES (?,?,?)"
            " ON CONFLICT(attempt_id) DO UPDATE SET rating=excluded.rating, comment=excluded.comment",
            (attempt_id, rating, comment.strip()[:200]),
        )


def get_feedback(attempt_id: int) -> dict[str, Any] | None:
    """Nhận xét đã lưu của một lượt làm, nếu có."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM feedback WHERE attempt_id=?", (attempt_id,)).fetchone()
    return dict(row) if row else None


def quiz_feedback(quiz_id: int) -> list[dict[str, Any]]:
    """Mọi nhận xét học sinh của một đề, mới nhất trước."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT f.*, a.student_name, a.score, a.total FROM feedback f JOIN attempts a ON a.id=f.attempt_id"
            " WHERE a.quiz_id=? ORDER BY f.created_at DESC",
            (quiz_id,),
        ).fetchall()
    return [dict(r) | {"label": RATING_LABEL.get(r["rating"], "")} for r in rows]


def quiz_report(quiz_id: int) -> dict[str, Any]:
    """Thống kê cho giáo viên: từng lượt làm và tỉ lệ sai theo câu."""
    with connect() as conn:
        attempts = conn.execute(
            "SELECT a.*, (SELECT COUNT(*) FROM attempts b WHERE b.quiz_id=a.quiz_id"
            " AND lower(trim(b.student_name))=lower(trim(a.student_name)) AND b.id<a.id) + 1 AS lan"
            " FROM attempts a WHERE a.quiz_id=? ORDER BY a.created_at DESC", (quiz_id,)
        ).fetchall()
        wrong = conn.execute(
            "SELECT q.position, q.prompt, q.topic, COUNT(a.id) AS n, SUM(1-a.is_correct) AS wrong"
            " FROM questions q LEFT JOIN answers a ON a.question_id=q.id"
            " WHERE q.quiz_id=? GROUP BY q.id ORDER BY q.position",
            (quiz_id,),
        ).fetchall()
        hint_count = conn.execute(
            "SELECT COUNT(*) AS n FROM hints h JOIN attempts a ON a.id=h.attempt_id WHERE a.quiz_id=?",
            (quiz_id,),
        ).fetchone()["n"]
    rows = [dict(a) for a in attempts]
    avg = round(sum(r["score"] / r["total"] for r in rows if r["total"]) / len(rows) * 100) if rows else 0
    topics = Counter()
    for w in wrong:
        if w["topic"] and w["wrong"]:
            topics[w["topic"]] += int(w["wrong"])
    feedback = quiz_feedback(quiz_id)
    liked = sum(1 for f in feedback if f["rating"] == 3)
    return {
        "attempts": rows,
        "per_question": [dict(w) for w in wrong],
        "average_pct": avg,
        "hint_count": hint_count,
        "weak_topics": topics.most_common(3),
        "feedback": feedback,
        "liked_pct": round(liked / len(feedback) * 100) if feedback else None,
    }


def delete_attempt(attempt_id: int) -> None:
    """Xóa một lượt làm cùng câu trả lời, gợi ý, nhận xét."""
    with connect() as conn:
        conn.execute("DELETE FROM attempts WHERE id=?", (attempt_id,))


DUPLICATE_WINDOW_MINUTES = 10


def dedupe_quiz(quiz_id: int) -> int:
    """Xóa các lượt trùng do bấm nộp nhiều lần: cùng tên, cùng điểm, cùng toàn bộ câu trả lời, cách nhau dưới 10 phút.
    Giữ lượt sớm nhất, nhưng ưu tiên giữ lượt có nhận xét hoặc gợi ý. Trả về số lượt đã xóa."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT a.id, a.student_name, a.score, a.created_at,"
            " (SELECT COUNT(*) FROM feedback f WHERE f.attempt_id=a.id) +"
            " (SELECT COUNT(*) FROM hints h WHERE h.attempt_id=a.id) AS extra,"
            " (SELECT group_concat(given, '|') FROM (SELECT given FROM answers x WHERE x.attempt_id=a.id ORDER BY question_id)) AS vec"
            " FROM attempts a WHERE a.quiz_id=? ORDER BY a.student_name, a.created_at",
            (quiz_id,),
        ).fetchall()
    from datetime import datetime

    groups: dict[tuple[str, float], list[Any]] = {}
    for r in rows:
        key = (r["student_name"].strip().lower(), float(r["score"]), r["vec"] or "")
        groups.setdefault(key, []).append(r)
    to_delete: list[int] = []
    for members in groups.values():
        cluster: list[Any] = []
        last = None
        for r in members + [None]:
            t = datetime.fromisoformat(r["created_at"]) if r else None
            if r is None or (last is not None and (t - last).total_seconds() > DUPLICATE_WINDOW_MINUTES * 60):
                if len(cluster) > 1:
                    keep = max(cluster, key=lambda x: (x["extra"], -x["id"]))
                    to_delete += [x["id"] for x in cluster if x["id"] != keep["id"]]
                cluster = []
            if r is not None:
                cluster.append(r)
                last = t
    with connect() as conn:
        conn.executemany("DELETE FROM attempts WHERE id=?", [(i,) for i in to_delete])
    return len(to_delete)


def set_game_result(attempt_id: int, points: int, seconds: int) -> None:
    """Ghi điểm và thời gian chơi game cho một lượt."""
    with connect() as conn:
        conn.execute("UPDATE attempts SET game_points=?, game_seconds=? WHERE id=?", (int(points), int(seconds), attempt_id))


LEADERBOARD_MAX_ROWS = 200
CLASS_TOKEN_RE = re.compile(r"^(?P<ten>.*?)[\s,-]+(?P<lop>\d[\w.\-/]*)$")


def split_class(student_name: str) -> tuple[str, str]:
    """'Minh 4.3' -> ('Minh', '4.3'); tên không có lớp thì lớp để trống."""
    m = CLASS_TOKEN_RE.match(student_name.strip())
    if not m:
        return student_name.strip(), ""
    return m.group("ten").strip(), m.group("lop").upper()


def leaderboard(quiz_id: int, limit: int = LEADERBOARD_MAX_ROWS) -> list[dict[str, Any]]:
    """Bảng xếp hạng game cả lớp: điểm cao trước, nhanh hơn xếp trên; mỗi em lấy lượt tốt nhất."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT student_name, game_points AS points, game_seconds AS seconds, score, total FROM ("
            "  SELECT *, ROW_NUMBER() OVER (PARTITION BY lower(trim(student_name))"
            "         ORDER BY game_points DESC, game_seconds ASC, id DESC) AS rn"
            "  FROM attempts WHERE quiz_id=? AND game_points IS NOT NULL)"
            " WHERE rn=1 ORDER BY points DESC, seconds ASC LIMIT ?",
            (quiz_id, limit),
        ).fetchall()
    result = []
    for r in rows:
        ten, lop = split_class(r["student_name"])
        result.append({**dict(r), "ten": ten, "lop": lop})
    return result
