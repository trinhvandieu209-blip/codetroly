"""Cấu hình ứng dụng, đọc từ biến môi trường."""
import logging
import os
import secrets
from pathlib import Path

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("APP_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "tro_ly_tin_hoc.db"
SEED_PATH = BASE_DIR / "data" / "seed_questions.json"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Nhiều khóa (mỗi khóa từ một tài khoản Google) để xoay vòng khi một khóa hết hạn mức miễn phí
GEMINI_API_KEYS = [k.strip() for k in os.getenv("GEMINI_API_KEYS", GEMINI_API_KEY).split(",") if k.strip()]
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
# Khi model chính quá tải (503/504) thì lần lượt thử các model dự phòng
GEMINI_FALLBACK_MODELS = [m for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-flash-lite-latest,gemini-3.5-flash").split(",") if m]
# Chấm, gợi ý, kế hoạch: nhiều lượt nhỏ -> ưu tiên model nhanh, hạn mức rộng
GEMINI_FAST_MODELS = [m for m in os.getenv("GEMINI_FAST_MODELS", "gemini-flash-lite-latest,gemini-3-flash-preview,gemini-3.5-flash").split(",") if m]
GEMINI_TIMEOUT_MS = 90_000
GEMINI_MAX_CONCURRENCY = 3  # gói miễn phí tính lượt/phút, xếp hàng để cả lớp nộp cùng lúc không bị 429
GEMINI_RETRY_WAIT_S = 2.5
GEMINI_QUEUE_WAIT_S = 45  # chờ hàng AI tối đa, quá thì chấm ngoại tuyến
MAX_FORM_BYTES = 256 * 1024  # body tối đa cho POST thường (không phải tải tệp)

MAX_UPLOAD_MB = 20
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".txt", ".docx"}
MAX_QUESTIONS = 20
MIN_QUESTIONS = 3
DEFAULT_QUESTIONS = 10
QUIZ_CODE_LENGTH = 6
MAX_HINTS_PER_QUESTION = 3
PIN_MAX_FAILURES = 5
PIN_LOCK_SECONDS = 300
STUDENT_RATE_LIMIT_PER_MINUTE = 150  # cả lớp sau một NAT trường
HINT_RATE_LIMIT_PER_MINUTE = 20  # theo từng lượt làm
TRUST_PROXY = os.getenv("TRUST_PROXY", "") == "1"  # chỉ bật khi chạy sau reverse proxy (Railway)


def _secret_key() -> str:
    """Khóa ký cookie: lấy từ môi trường, thiếu thì sinh ngẫu nhiên mỗi lần chạy (cookie cũ sẽ mất hiệu lực)."""
    value = os.getenv("SECRET_KEY", "")
    if len(value) >= 32:
        return value
    log.warning("SECRET_KEY chưa đặt hoặc quá ngắn: dùng khóa ngẫu nhiên tạm, phiên đăng nhập sẽ mất khi khởi động lại")
    return secrets.token_hex(32)


def _teacher_pin() -> str:
    """PIN giáo viên: lấy từ môi trường, thiếu thì sinh ngẫu nhiên và ghi ra log để người vận hành biết."""
    value = os.getenv("TEACHER_PIN", "").strip()
    if len(value) >= 4:
        return value
    generated = f"{secrets.randbelow(10**6):06d}"
    log.warning("TEACHER_PIN chưa đặt: PIN tạm thời cho phiên này là %s", generated)
    return generated


SECRET_KEY = _secret_key()
TEACHER_PIN = _teacher_pin()


def ensure_dirs() -> None:
    """Tạo thư mục dữ liệu và thư mục tải lên nếu chưa có."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def has_ai() -> bool:
    """Cho biết đã cấu hình khóa Gemini hay chưa."""
    return bool(GEMINI_API_KEYS)
