"""Trợ lý Tin học AI - ứng dụng FastAPI."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from config import BASE_DIR, MAX_FORM_BYTES, MAX_UPLOAD_BYTES, SECRET_KEY
from db import init_db
from routes import student, teacher

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Khởi tạo CSDL khi server lên."""
    init_db()
    yield


app = FastAPI(title="Trợ lý Tin học AI", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.middleware("http")
async def _guard_posts(request: Request, call_next):
    """Chặn sớm body quá lớn và POST từ trang web khác (CSRF) trước khi đọc form."""
    if request.method == "POST":
        is_upload = request.url.path == "/gv/tai-lieu" or request.url.path.endswith("/luu")
        limit = MAX_UPLOAD_BYTES + 64 * 1024 if is_upload else MAX_FORM_BYTES
        try:
            declared = int(request.headers.get("content-length") or (limit + 1))
        except ValueError:
            declared = limit + 1
        if declared > limit:
            return RedirectResponse("/", status_code=303)
        origin = request.headers.get("origin")
        if origin and origin.split("://", 1)[-1].split("/", 1)[0] != request.headers.get("host", ""):
            return RedirectResponse("/", status_code=303)
    return await call_next(request)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax", max_age=60 * 60 * 3)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(teacher.router)
app.include_router(student.router)


@app.exception_handler(RequestValidationError)
async def _validation_redirect(request: Request, exc: RequestValidationError):
    """Đường dẫn hoặc form sai kiểu (ví dụ id không phải số): đưa về trang phù hợp thay vì lỗi kỹ thuật."""
    if request.url.path.startswith("/gv"):
        return RedirectResponse("/gv", status_code=303)
    return RedirectResponse("/", status_code=303)


@app.get("/health")
def health() -> dict[str, str]:
    """Kiểm tra sống cho hosting."""
    return {"status": "ok"}
