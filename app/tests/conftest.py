"""Fixture dùng chung: CSDL tạm, không gọi Gemini."""
import importlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    """Client FastAPI với thư mục dữ liệu tạm và chế độ không AI."""
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("TEACHER_PIN", "9999")
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    for name in list(sys.modules):
        if name in {"config", "db", "main"} or name.startswith(("ai.", "services.", "routes.")) or name in {"ai", "services", "routes"}:
            del sys.modules[name]
    main = importlib.import_module("main")
    importlib.import_module("services.ratelimit").reset()
    from fastapi.testclient import TestClient

    with TestClient(main.app) as client:
        yield client


@pytest.fixture()
def teacher(app_client):
    """Client đã đăng nhập giáo viên."""
    r = app_client.post("/gv/dang-nhap", data={"pin": "9999"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/gv"
    return app_client
