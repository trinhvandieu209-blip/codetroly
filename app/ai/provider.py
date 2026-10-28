"""Lớp gọi mô hình AI. Có chế độ ngoại tuyến để ứng dụng vẫn chạy khi chưa có khóa."""
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from config import (
    GEMINI_API_KEYS,
    GEMINI_FALLBACK_MODELS,
    GEMINI_FAST_MODELS,
    GEMINI_MAX_CONCURRENCY,
    GEMINI_MODEL,
    GEMINI_QUEUE_WAIT_S,
    GEMINI_RETRY_WAIT_S,
    GEMINI_TIMEOUT_MS,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Attachment:
    """Tệp tài liệu gửi kèm prompt."""

    data: bytes
    mime_type: str


class AIError(Exception):
    """Lỗi khi gọi mô hình hoặc kết quả không hợp lệ."""


def parse_json_block(text: str) -> dict[str, Any]:
    """Tách khối JSON đầu tiên trong văn bản trả về của mô hình."""
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise AIError("Mô hình không trả về JSON")
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AIError(f"JSON không hợp lệ: {exc}") from exc


class GeminiProvider:
    """Gọi Gemini qua SDK google-genai; xoay vòng nhiều khóa và nhiều model khi gặp hạn mức."""

    RETRYABLE_CODES = {429, 500, 503, 504}
    _gate = threading.BoundedSemaphore(GEMINI_MAX_CONCURRENCY)

    def __init__(self, api_keys: Optional[list[str]] = None, model: str = GEMINI_MODEL) -> None:
        from google import genai
        from google.genai import types

        keys = api_keys or GEMINI_API_KEYS
        opts = types.HttpOptions(timeout=GEMINI_TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=1))
        self._clients = [genai.Client(api_key=k, http_options=opts) for k in keys]
        self._models = [model] + [m for m in GEMINI_FALLBACK_MODELS if m != model]
        self._turn = 0
        self._turn_lock = threading.Lock()

    @classmethod
    def _is_retryable(cls, exc: Exception) -> bool:
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        return code in cls.RETRYABLE_CODES

    @staticmethod
    def _is_key_problem(exc: Exception) -> bool:
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        return code in {400, 401, 403}

    def _rotated_clients(self) -> list[Any]:
        """Mỗi lượt gọi bắt đầu từ một khóa khác nhau để chia đều tải giữa các khóa."""
        with self._turn_lock:
            start = self._turn % max(1, len(self._clients))
            self._turn += 1
        return self._clients[start:] + self._clients[:start]

    def generate_json(
        self, prompt: str, attachment: Optional[Attachment] = None, fast: bool = False
    ) -> dict[str, Any]:
        """Gửi prompt (và tệp nếu có); fast=True dùng dãy model nhanh cho các lượt nhỏ, lặp lại nhiều."""
        from google.genai import types

        contents: list[Any] = []
        if attachment is not None:
            contents.append(types.Part.from_bytes(data=attachment.data, mime_type=attachment.mime_type))
        contents.append(prompt)
        config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.4)
        models = GEMINI_FAST_MODELS if fast and GEMINI_FAST_MODELS else self._models
        if not self._gate.acquire(timeout=GEMINI_QUEUE_WAIT_S):
            raise AIError("AI đang bận, hàng chờ quá dài")
        try:
            return self._call_models(contents, config, models)
        finally:
            self._gate.release()

    def _call_models(self, contents: list[Any], config: Any, models: list[str]) -> dict[str, Any]:
        """Thử từng model với từng khóa; tất cả đều quá tải thì chờ rồi thử lại một vòng nữa."""
        last_error: Optional[Exception] = None
        for attempt in (1, 2):
            for model in models:
                for client in self._rotated_clients():
                    try:
                        response = client.models.generate_content(model=model, contents=contents, config=config)
                    except Exception as exc:  # SDK ném nhiều loại lỗi khác nhau
                        last_error = exc
                        log.warning("Model %s lỗi (vòng %d): %s", model, attempt, str(exc)[:120])
                        if self._is_key_problem(exc):
                            continue  # khóa này hỏng hoặc bị thu hồi, thử khóa khác
                        if not self._is_retryable(exc):
                            raise AIError(f"Không gọi được AI: {exc}") from exc
                        continue
                    if response.text:
                        return parse_json_block(response.text)
                    last_error = AIError(f"{model} trả về nội dung rỗng")
            if attempt == 1:
                time.sleep(GEMINI_RETRY_WAIT_S)
        raise AIError(f"Không gọi được AI: {last_error}")


_provider: Optional[GeminiProvider] = None


def get_provider() -> Optional[GeminiProvider]:
    """Trả về provider dùng chung, hoặc None nếu chưa cấu hình khóa."""
    global _provider
    if not GEMINI_API_KEYS:
        return None
    if _provider is None:
        _provider = GeminiProvider()
    return _provider
