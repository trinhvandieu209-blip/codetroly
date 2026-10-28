"""Tạo, lưu và truy vấn bộ câu hỏi."""
import json
import secrets
import string
from typing import Any

from config import QUIZ_CODE_LENGTH
from db import connect

CODE_ALPHABET = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"


def new_code() -> str:
    """Sinh mã bài ngắn, dễ đọc, không có O/I/0/1."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(QUIZ_CODE_LENGTH))


def create_quiz(material_id: int | None, grade: str, quiz: dict[str, Any], source: str) -> int:
    """Lưu quiz ở trạng thái nháp, trả về id."""
    with connect() as conn:
        code = new_code()
        while conn.execute("SELECT 1 FROM quizzes WHERE code=?", (code,)).fetchone():
            code = new_code()
        cur = conn.execute(
            "INSERT INTO quizzes (material_id, title, grade, code, source) VALUES (?,?,?,?,?)",
            (material_id, quiz["title"], grade, code, source),
        )
        quiz_id = int(cur.lastrowid)
        conn.executemany(
            "INSERT INTO questions (quiz_id, position, qtype, prompt, options_json, answer, explanation, topic, image_path)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    quiz_id,
                    q["position"],
                    q["qtype"],
                    q["prompt"],
                    json.dumps(q["options"], ensure_ascii=False),
                    q["answer"],
                    q["explanation"],
                    q["topic"],
                    q.get("image_path", ""),
                )
                for q in quiz["questions"]
            ],
        )
        return quiz_id


def _row_to_question(row: Any) -> dict[str, Any]:
    q = dict(row)
    q["options"] = json.loads(q.pop("options_json") or "[]")
    return q


def get_quiz(quiz_id: int) -> dict[str, Any] | None:
    """Lấy quiz kèm danh sách câu hỏi."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
        if not row:
            return None
        qs = conn.execute("SELECT * FROM questions WHERE quiz_id=? ORDER BY position", (quiz_id,)).fetchall()
    quiz = dict(row)
    quiz["questions"] = [_row_to_question(q) for q in qs]
    return quiz


def get_quiz_by_code(code: str) -> dict[str, Any] | None:
    """Tìm quiz đã phát hành theo mã."""
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM quizzes WHERE code=? AND status='published'", (code.strip().upper(),)
        ).fetchone()
    return get_quiz(int(row["id"])) if row else None


def list_quizzes() -> list[dict[str, Any]]:
    """Danh sách quiz kèm số lượt làm."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT q.*, (SELECT COUNT(*) FROM attempts a WHERE a.quiz_id=q.id) AS attempt_count,"
            " (SELECT COUNT(*) FROM questions s WHERE s.quiz_id=q.id) AS question_count"
            " FROM quizzes q ORDER BY q.id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_questions(quiz_id: int, edits: list[dict[str, Any]]) -> None:
    """Giáo viên sửa nội dung câu hỏi sau khi AI sinh."""
    with connect() as conn:
        for e in edits:
            conn.execute(
                "UPDATE questions SET prompt=?, answer=?, explanation=?, options_json=?, image_path=? WHERE id=? AND quiz_id=?",
                (
                    e["prompt"],
                    e["answer"],
                    e["explanation"],
                    json.dumps(e["options"], ensure_ascii=False),
                    e.get("image_path", ""),
                    e["id"],
                    quiz_id,
                ),
            )


def set_status(quiz_id: int, status: str) -> None:
    """Đổi trạng thái draft/published/closed."""
    with connect() as conn:
        conn.execute("UPDATE quizzes SET status=? WHERE id=?", (status, quiz_id))


def set_title(quiz_id: int, title: str) -> None:
    """Đổi tên đề theo ý giáo viên."""
    with connect() as conn:
        conn.execute("UPDATE quizzes SET title=? WHERE id=?", (title, quiz_id))


def delete_quiz(quiz_id: int) -> None:
    """Xóa quiz và dữ liệu liên quan."""
    with connect() as conn:
        conn.execute("DELETE FROM quizzes WHERE id=?", (quiz_id,))


def delete_question(quiz_id: int, question_id: int) -> int:
    """Xóa một câu và đánh lại số thứ tự; trả về số câu còn lại."""
    with connect() as conn:
        conn.execute("DELETE FROM questions WHERE id=? AND quiz_id=?", (question_id, quiz_id))
        rows = conn.execute("SELECT id FROM questions WHERE quiz_id=? ORDER BY position", (quiz_id,)).fetchall()
        for pos, row in enumerate(rows, start=1):
            conn.execute("UPDATE questions SET position=? WHERE id=?", (pos, row["id"]))
        conn.execute(
            "UPDATE attempts SET total=(SELECT COUNT(*) FROM answers x WHERE x.attempt_id=attempts.id),"
            " score=(SELECT COALESCE(SUM(is_correct),0) FROM answers x WHERE x.attempt_id=attempts.id)"
            " WHERE quiz_id=?",
            (quiz_id,),
        )
        return len(rows)
