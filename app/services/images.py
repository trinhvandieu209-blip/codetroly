"""Ảnh minh họa gắn vào câu hỏi (giáo viên tải lên)."""
import uuid
from pathlib import Path

from config import UPLOAD_DIR

IMAGE_DIR = UPLOAD_DIR / "cau-hoi"
MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_TOTAL_BYTES = 150 * 1024 * 1024  # ổ /data 500 MB, chừa chỗ cho CSDL và tài liệu
MAGIC = {b"\x89PNG": ".png", b"\xff\xd8\xff": ".jpg", b"GIF8": ".gif"}


class ImageError(ValueError):
    """Ảnh không hợp lệ."""


def detect_ext(data: bytes) -> str:
    """Nhận dạng PNG/JPG/GIF theo byte đầu, không tin phần mở rộng tên tệp."""
    for magic, ext in MAGIC.items():
        if data[: len(magic)] == magic:
            return ext
    raise ImageError("Ảnh phải là PNG, JPG hoặc GIF")


def save_image(data: bytes) -> str:
    """Lưu ảnh với tên ngẫu nhiên, trả về tên tệp (không phải đường dẫn đầy đủ)."""
    if not data:
        raise ImageError("Chưa chọn ảnh")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError("Ảnh tối đa 3 MB")
    if total_bytes() + len(data) > MAX_TOTAL_BYTES:
        raise ImageError("Kho ảnh đã đầy, hãy xóa bớt ảnh ở các đề cũ")
    name = f"{uuid.uuid4().hex}{detect_ext(data)}"
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    (IMAGE_DIR / name).write_bytes(data)
    return name


def total_bytes() -> int:
    """Tổng dung lượng ảnh đang lưu."""
    if not IMAGE_DIR.exists():
        return 0
    return sum(p.stat().st_size for p in IMAGE_DIR.iterdir() if p.is_file())


def image_file(name: str) -> Path | None:
    """Đường dẫn tệp ảnh nếu tên hợp lệ và tồn tại; chặn mọi ký tự đường dẫn."""
    if not name or not name.replace(".", "").replace("-", "").isalnum() or "/" in name or ".." in name:
        return None
    path = IMAGE_DIR / name
    return path if path.is_file() else None


def delete_image(name: str) -> None:
    """Xóa tệp ảnh nếu có."""
    path = image_file(name)
    if path:
        path.unlink(missing_ok=True)
