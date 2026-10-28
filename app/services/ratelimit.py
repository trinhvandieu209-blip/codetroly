"""Giới hạn tần suất đơn giản trong bộ nhớ, đủ cho một lớp học dùng chung một server."""
import threading
import time
from collections import defaultdict, deque

from config import PIN_LOCK_SECONDS, PIN_MAX_FAILURES, STUDENT_RATE_LIMIT_PER_MINUTE

_lock = threading.Lock()
_pin_failures: dict[str, deque[float]] = defaultdict(deque)
_hits: dict[str, deque[float]] = defaultdict(deque)


def _prune(bucket: deque[float], window: float, now: float) -> None:
    while bucket and now - bucket[0] > window:
        bucket.popleft()


def pin_locked(ip: str) -> bool:
    """IP đã sai PIN quá số lần cho phép trong cửa sổ khóa chưa."""
    now = time.monotonic()
    with _lock:
        bucket = _pin_failures[ip]
        _prune(bucket, PIN_LOCK_SECONDS, now)
        return len(bucket) >= PIN_MAX_FAILURES


def record_pin_failure(ip: str) -> None:
    """Ghi nhận một lần sai PIN."""
    with _lock:
        _pin_failures[ip].append(time.monotonic())


def clear_pin_failures(ip: str) -> None:
    """Xóa lịch sử sai sau khi đăng nhập đúng."""
    with _lock:
        _pin_failures.pop(ip, None)


def allow(key: str, limit: int = STUDENT_RATE_LIMIT_PER_MINUTE) -> bool:
    """Cho phép tối đa `limit` lượt mỗi phút cho một khóa (thường là IP)."""
    now = time.monotonic()
    with _lock:
        bucket = _hits[key]
        _prune(bucket, 60.0, now)
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


def reset() -> None:
    """Dùng trong kiểm thử."""
    with _lock:
        _pin_failures.clear()
        _hits.clear()
