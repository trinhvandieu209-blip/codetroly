"""Tiện ích dùng chung cho các router."""
from fastapi import Request
from fastapi.templating import Jinja2Templates

from config import BASE_DIR, TRUST_PROXY, has_ai

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def gio(value: str) -> str:
    """'2026-10-27 14:57:40' -> '14:57 27/10'."""
    try:
        ngay, gio_phut = str(value).split(" ")
        y, m, d = ngay.split("-")
        return f"{gio_phut[:5]} {d}/{m}"
    except ValueError:
        return str(value)


templates.env.filters["gio"] = gio


def range_shuffled(n: int, seed: int) -> list[int]:
    """Thứ tự vế phải xáo trộn nhưng ổn định theo id câu, để tải lại trang không đổi chỗ."""
    import random

    order = list(range(int(n)))
    random.Random(int(seed)).shuffle(order)
    return order


def parse_match_filter(given: str) -> dict[int, int]:
    from ai.grader import parse_match

    return parse_match(given)


templates.env.filters["range_shuffled"] = range_shuffled
templates.env.filters["parse_match"] = parse_match_filter


def render(request: Request, name: str, **context):
    """Render template kèm các biến chung (trạng thái AI, thông báo flash)."""
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(
        request, name, {"request": request, "has_ai": has_ai(), "flash": flash, **context}
    )


def client_ip(request: Request) -> str:
    """IP thật của người dùng. Chỉ tin X-Forwarded-For (phần tử cuối do proxy thêm) khi TRUST_PROXY=1."""
    direct = request.client.host if request.client else "?"
    if not TRUST_PROXY:
        return direct
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[-1].strip() if forwarded else direct


def set_flash(request: Request, message: str, kind: str = "ok") -> None:
    """Ghi thông báo một lần để hiện ở trang kế tiếp."""
    request.session["flash"] = {"text": message, "kind": kind}
