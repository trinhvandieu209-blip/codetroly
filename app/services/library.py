"""Thư viện sách giáo khoa có sẵn: cắt đúng trang bài học để gửi cho AI."""
import io
import json
from pathlib import Path
from typing import Any

from ai.provider import Attachment
from config import BASE_DIR

INDEX_PATH = BASE_DIR / "data" / "sgk_index.json"
SGK_DIR = Path(BASE_DIR.parent / "tailieu")


def load_index() -> dict[str, Any]:
    """Đọc chỉ mục SGK: {grade: {file, lessons: [{id, title, pages:[a,b], semester}]}}."""
    if not INDEX_PATH.exists():
        return {}
    with open(INDEX_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def list_lessons(grade: str) -> list[dict[str, Any]]:
    """Danh sách bài học của một khối."""
    return load_index().get(grade, {}).get("lessons", [])


def find_lessons(grade: str, lesson_ids: list[str]) -> list[dict[str, Any]]:
    """Lấy các bài theo id, giữ thứ tự trong sách."""
    wanted = set(lesson_ids)
    return [l for l in list_lessons(grade) if l["id"] in wanted]


def semester_lessons(grade: str, semester: int) -> list[dict[str, Any]]:
    """Các bài thuộc một học kỳ, dùng cho đề ôn tập."""
    return [l for l in list_lessons(grade) if l.get("semester") == semester]


def extract_pages(pdf_path: Path, ranges: list[tuple[int, int]]) -> bytes:
    """Cắt các khoảng trang (1-based, bao gồm 2 đầu) thành một PDF nhỏ."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    for start, end in ranges:
        for page_no in range(start, min(end, len(reader.pages)) + 1):
            writer.add_page(reader.pages[page_no - 1])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def lessons_attachment(grade: str, lessons: list[dict[str, Any]]) -> Attachment:
    """Tạo Attachment PDF chỉ chứa các trang của những bài đã chọn."""
    info = load_index().get(grade)
    if not info or not lessons:
        raise ValueError("Không có bài học để tạo đề")
    pdf_path = SGK_DIR / info["file"]
    ranges = [(int(l["pages"][0]), int(l["pages"][1])) for l in lessons]
    return Attachment(data=extract_pages(pdf_path, ranges), mime_type="application/pdf")


def lessons_title(lessons: list[dict[str, Any]], grade: str, semester: int | None) -> str:
    """Tên quiz gợi ý từ danh sách bài."""
    if semester:
        return f"Ôn tập học kỳ {semester} - Tin học {grade}"
    if len(lessons) == 1:
        return f"{lessons[0]['title']} - Tin học {grade}"
    return f"Ôn tập {len(lessons)} bài - Tin học {grade}"
