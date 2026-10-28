"""Lưu và đọc tài liệu bài học do giáo viên tải lên."""
import mimetypes
import uuid
from pathlib import Path
from typing import Any

from ai.provider import Attachment
from config import ALLOWED_EXTENSIONS, MAX_UPLOAD_MB, UPLOAD_DIR
from db import connect

MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".txt": "text/plain",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class MaterialError(ValueError):
    """Tệp không hợp lệ."""


def validate_upload(filename: str, size: int) -> str:
    """Kiểm tra phần mở rộng và dung lượng, trả về mime type."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise MaterialError("Chỉ nhận PDF, ảnh PNG/JPG, Word .docx hoặc .txt")
    if size > MAX_UPLOAD_MB * 1024 * 1024:
        raise MaterialError(f"Tệp quá lớn, tối đa {MAX_UPLOAD_MB} MB")
    if size == 0:
        raise MaterialError("Tệp rỗng")
    return MIME_BY_EXT.get(ext) or mimetypes.guess_type(filename)[0] or "application/octet-stream"


def save_material(title: str, grade: str, filename: str, data: bytes) -> int:
    """Ghi tệp vào thư mục uploads và tạo bản ghi, trả về id."""
    mime = validate_upload(filename, len(data))
    safe_name = f"{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
    stored = UPLOAD_DIR / safe_name
    stored.write_bytes(data)
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO materials (title, grade, filename, stored_path, mime_type) VALUES (?,?,?,?,?)",
            (title.strip(), grade, filename, str(stored), mime),
        )
        return int(cur.lastrowid)


def list_materials() -> list[dict[str, Any]]:
    """Danh sách tài liệu mới nhất trước."""
    with connect() as conn:
        rows = conn.execute("SELECT * FROM materials ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def get_material(material_id: int) -> dict[str, Any] | None:
    """Lấy một tài liệu theo id."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()
    return dict(row) if row else None


MAX_DOCX_XML_BYTES = 30 * 1024 * 1024


def _docx_to_text(data: bytes) -> bytes:
    """Rút văn bản từ .docx để gửi cho AI dưới dạng text; từ chối tệp giả hoặc quá lớn khi giải nén."""
    import io
    import re
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            info = zf.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_XML_BYTES:
                raise MaterialError("Tệp Word quá lớn khi giải nén")
            xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise MaterialError("Tệp .docx không hợp lệ") from exc
    text = re.sub(r"</w:p>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", text)
    return text.encode("utf-8")


def load_attachment(material: dict[str, Any]) -> Attachment:
    """Đọc tệp thành Attachment gửi cho AI; docx được chuyển thành text."""
    path = Path(material["stored_path"])
    if not path.exists():
        raise MaterialError("Tệp gốc không còn trên máy chủ, hãy tải lại")
    data = path.read_bytes()
    if material["mime_type"].endswith("wordprocessingml.document"):
        return Attachment(data=_docx_to_text(data), mime_type="text/plain")
    return Attachment(data=data, mime_type=material["mime_type"])
