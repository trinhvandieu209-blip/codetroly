"""Kiểm thử chấm điểm ngoại tuyến và phân tích JSON."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from ai.grader import grade_mcq, grade_short_offline, normalize_text
from ai.provider import AIError, parse_json_block
from ai.quiz_gen import normalize_quiz
from ai.tutor import hint_offline, leaks_answer


def test_normalize_text_bo_dau_va_ky_tu_thua():
    assert normalize_text("Hàng phím Cơ Sở!") == "hang phim co so"


@pytest.mark.parametrize("given,expected", [("B", True), ("b. Minh muốn", True), ("A", False), ("", False)])
def test_grade_mcq_so_chu_cai_dau(given, expected):
    assert grade_mcq("B", given) is expected


@pytest.mark.parametrize(
    "answer,given,expected",
    [
        ("thông tin", "Thong tin", True),
        ("hàng phím cơ sở", "hang phim co so", True),
        ("hàng phím cơ sở", "phím cơ sở", True),
        ("thông tin", "quyết định", False),
        ("thông tin", "", False),
        ("thông tin", "n", False),
        ("thông tin", "thông tin và quyết định", True),
    ],
)
def test_grade_short_offline_khop_mem(answer, given, expected):
    assert grade_short_offline(answer, given) is expected


def test_parse_json_block_chap_nhan_code_fence():
    assert parse_json_block('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_block_loi_khi_khong_co_json():
    with pytest.raises(AIError):
        parse_json_block("xin chào")


def test_normalize_quiz_tu_choi_dap_an_khong_khop_lua_chon():
    payload = {"questions": [{"qtype": "mcq", "prompt": "?", "options": ["A. x", "B. y"], "answer": "C"}]}
    with pytest.raises(AIError):
        normalize_quiz(payload, "t")


def test_normalize_quiz_chuan_hoa_cau_hop_le():
    payload = {"title": "T", "questions": [{"qtype": "mcq", "prompt": "?", "options": ["A. x", "B. y"], "answer": "b. y", "explanation": "e"}]}
    quiz = normalize_quiz(payload, "x")
    assert quiz["questions"][0]["answer"] == "B" and quiz["questions"][0]["position"] == 1


def test_hint_offline_khong_lo_dap_an():
    q = {"qtype": "mcq", "topic": "Bàn phím", "explanation": "Hai phím F và J có gờ", "answer": "B"}
    for level in (1, 2, 3):
        hint = hint_offline(q, level)
        assert "F và J" not in hint and "Đáp án" not in hint and "Bàn phím" in hint


def test_hint_offline_cau_ngan_chi_lo_so_tu_va_chu_dau():
    q = {"qtype": "short", "topic": "Thông tin", "explanation": "x", "answer": "hàng phím cơ sở"}
    hint = hint_offline(q, 3)
    assert "4 từ" in hint and '"H"' in hint and "hàng phím cơ sở" not in hint
    assert '"T"' not in hint_offline({"qtype": "short", "topic": "x", "explanation": "", "answer": "thông tin"}, 3)


def test_relabel_options_ep_ve_abc():
    payload = {"questions": [{"qtype": "mcq", "prompt": "?", "options": ["1) x", "y", "C. z"], "answer": "B"}]}
    quiz = normalize_quiz(payload, "t")
    assert quiz["questions"][0]["options"] == ["A. x", "B. y", "C. z"]


def test_hint_offline_dap_an_1_ky_tu_khong_lo_chu_dau():
    q = {"qtype": "short", "topic": "Số", "explanation": "x", "answer": "5"}
    assert '"5"' not in hint_offline(q, 3)


def test_leaks_answer_bat_duoc_lua_chon_dung_va_dap_an_ngan():
    mcq = {"qtype": "mcq", "options": ["A. Dạng chữ", "B. Dạng âm thanh", "C. Dạng hình ảnh"], "answer": "B"}
    assert leaks_answer(mcq, "Em nghĩ xem, đó là dạng âm thanh đấy") is True
    assert leaks_answer(mcq, "Em nhớ lại thông tin nghe được bằng tai là dạng gì?") is False
    short = {"qtype": "short", "answer": "hàng phím cơ sở"}
    assert leaks_answer(short, "Đó là hang phim co so") is True
    assert leaks_answer(short, "Hàng có hai phím F và J gọi là gì?") is False


def test_provider_chuyen_model_du_phong_khi_qua_tai(monkeypatch):
    from ai import provider as prov

    class Overloaded(Exception):
        code = 503

    calls = []

    class FakeModels:
        def generate_content(self, model, contents, config):
            calls.append(model)
            if model == "chinh":
                raise Overloaded("503 busy")
            return type("R", (), {"text": '{"ok": true}'})()

    p = prov.GeminiProvider.__new__(prov.GeminiProvider)
    p._clients = [type("C", (), {"models": FakeModels()})()]
    p._models = ["chinh", "phu"]
    p._turn = 0
    p._turn_lock = __import__("threading").Lock()
    monkeypatch.setattr(prov.time, "sleep", lambda s: None)
    assert p.generate_json("x") == {"ok": True} and calls == ["chinh", "phu"]


def test_provider_loi_khong_retry_thi_nem_ngay():
    from ai import provider as prov

    class Bad(Exception):
        code = 400

    class FakeModels:
        def generate_content(self, model, contents, config):
            raise Bad("400")

    p = prov.GeminiProvider.__new__(prov.GeminiProvider)
    p._clients = [type("C", (), {"models": FakeModels()})()]
    p._models = ["chinh", "phu"]
    p._turn = 0
    p._turn_lock = __import__("threading").Lock()
    with pytest.raises(prov.AIError):
        p.generate_json("x")


def test_grade_and_plan_gop_mot_luot_goi(monkeypatch):
    from ai import batch

    calls = []

    class Fake:
        def generate_json(self, prompt, attachment=None, fast=False):
            calls.append(prompt)
            return {"grades": [{"id": 2, "correct": True, "feedback": "Giỏi"}], "plan": "- Ngày 1: ôn"}

    monkeypatch.setattr(batch, "get_provider", lambda: Fake())
    quiz = {"grade": "3", "title": "T", "questions": [
        {"id": 1, "qtype": "mcq", "options": ["A. x", "B. y"], "answer": "A", "topic": "M1", "prompt": "?"},
        {"id": 2, "qtype": "short", "options": [], "answer": "thông tin", "topic": "M2", "prompt": "?"},
        {"id": 3, "qtype": "short", "options": [], "answer": "dạng chữ", "topic": "M3", "prompt": "?"},
    ]}
    graded, plan = batch.grade_and_plan(quiz, "Na", {1: "B", 2: "thong tin", 3: "abc"})
    assert len(calls) == 1 and plan == "- Ngày 1: ôn"
    assert [ok for _, _, ok, _ in graded] == [False, True, False]  # câu 3 AI bỏ sót -> chấm ngoại tuyến


def test_grade_and_plan_khong_ai_van_cham_duoc(monkeypatch):
    from ai import batch

    monkeypatch.setattr(batch, "get_provider", lambda: None)
    quiz = {"grade": "3", "title": "T", "questions": [
        {"id": 1, "qtype": "short", "options": [], "answer": "thông tin", "topic": "M2", "prompt": "?"}]}
    graded, plan = batch.grade_and_plan(quiz, "Na", {1: "Thong tin"})
    assert graded[0][2] is True and "Kế hoạch" in plan or "nắm chắc" in plan


def test_word_bank_luon_chua_dap_an_va_toi_da_5():
    from ai.quiz_gen import word_bank

    assert word_bank({"word_bank": ["a", "b", "c", "d", "e", "f"]}, "thông tin") == ["a", "b", "c", "d", "thông tin"]
    assert word_bank({}, "x") == []


def test_provider_xoay_vong_khoa_khi_khoa_dau_het_han_muc(monkeypatch):
    import threading

    from ai import provider as prov

    class Quota(Exception):
        code = 429

    used = []

    def make(name, ok):
        class M:
            def generate_content(self, model, contents, config):
                used.append(name)
                if not ok:
                    raise Quota("429")
                return type("R", (), {"text": '{"k": "%s"}' % name})()
        return type("C", (), {"models": M()})()

    p = prov.GeminiProvider.__new__(prov.GeminiProvider)
    p._clients = [make("k1", False), make("k2", True)]
    p._models = ["m"]
    p._turn = 0
    p._turn_lock = threading.Lock()
    monkeypatch.setattr(prov.time, "sleep", lambda s: None)
    assert p.generate_json("x") == {"k": "k2"} and used == ["k1", "k2"]
    assert p.generate_json("x") == {"k": "k2"} and used[-1:] == ["k2"]  # lượt sau bắt đầu từ khóa 2


def test_loc_gio_rut_gon():
    from routes.common import gio

    assert gio("2026-10-27 14:57:40") == "14:57 27/10" and gio("x") == "x"


def test_answer_letter_nhan_dap_an_dang_chu():
    from ai.quiz_gen import _answer_letter

    opts = ["A. Bàn phím", "B. Chuột", "C. Màn hình"]
    assert _answer_letter(opts, "Chuột") == "B" and _answer_letter(opts, "b.") == "B" and _answer_letter(opts, "B. Chuột") == "B"
    assert _answer_letter(opts, "Loa") is None


def test_grade_short_offline_khong_chap_nhan_liet_ke():
    assert grade_short_offline("dạng chữ", "dạng chữ dạng hình ảnh dạng âm thanh dạng số") is False
    assert grade_short_offline("dạng chữ", "dạng chữ ạ") is True


def test_provider_bo_qua_khoa_bi_thu_hoi(monkeypatch):
    import threading

    from ai import provider as prov

    class Revoked(Exception):
        code = 403

    def make(ok):
        class M:
            def generate_content(self, model, contents, config):
                if not ok:
                    raise Revoked("403")
                return type("R", (), {"text": '{"ok": 1}'})()
        return type("C", (), {"models": M()})()

    p = prov.GeminiProvider.__new__(prov.GeminiProvider)
    p._clients = [make(False), make(True)]
    p._models = ["m"]
    p._turn = 0
    p._turn_lock = threading.Lock()
    monkeypatch.setattr(prov.time, "sleep", lambda s: None)
    assert p.generate_json("x") == {"ok": 1}


def test_doi_gio_utc_chi_chay_mot_lan(tmp_path, monkeypatch):
    import importlib, sys

    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    for name in ("config", "db"):
        sys.modules.pop(name, None)
    db = importlib.import_module("db")
    db.init_db()  # DB mới: đánh dấu đã sửa, không có gì để dời
    with db.connect() as conn:
        conn.execute("DELETE FROM meta")
        conn.execute("INSERT INTO quizzes (title, grade, code, created_at) VALUES ('t','3','ABC123','2026-10-27 07:30:00')")
        conn.execute("INSERT INTO quizzes (title, grade, code, created_at) VALUES ('u','3','ABC124','2026-10-27 15:40:00')")
    db.init_db()
    db.init_db()  # lần 3 không được dời thêm
    with db.connect() as conn:
        rows = [r[0] for r in conn.execute("SELECT created_at FROM quizzes ORDER BY code").fetchall()]
        assert rows == ["2026-10-27 14:30:00", "2026-10-27 15:40:00"]


def test_cau_noi_ghep_duoc_chuan_hoa_va_cham():
    from ai.grader import grade_match_result, parse_match

    payload = {"questions": [{"qtype": "match", "prompt": "Nối", "pairs": [["Chuột", "Thiết bị vào"], ["Màn hình", "Thiết bị ra"], ["Chuột", "trùng"], ["x"]]}]}
    q = normalize_quiz(payload, "t")["questions"][0]
    assert q["options"] == [["Chuột", "Thiết bị vào"], ["Màn hình", "Thiết bị ra"]] and q["answer"] == ""
    assert parse_match("0:1,1:0,abc") == {0: 1, 1: 0}
    assert grade_match_result(q, "0:0,1:1")[0] is True
    ok, fb = grade_match_result(q, "0:1,1:0")
    assert ok is False and "0/2" in fb


def test_noi_ghep_thieu_cap_bi_tu_choi():
    with pytest.raises(AIError):
        normalize_quiz({"questions": [{"qtype": "match", "prompt": "Nối", "pairs": [["a", "b"]]}]}, "t")


def test_diem_game():
    from routes.student import game_points

    assert game_points(False, 1, 5) == 0
    assert game_points(True, 0, 1) == 160 and game_points(True, 20, 0) == 100 and game_points(True, 10, 3) == 155


def test_anh_cau_hoi_nhan_dang_va_chan_duong_dan(tmp_path, monkeypatch):
    from services import images

    monkeypatch.setattr(images, "IMAGE_DIR", tmp_path)
    name = images.save_image(b"\x89PNG\r\n" + b"0" * 10)
    assert name.endswith(".png") and images.image_file(name) is not None
    with pytest.raises(images.ImageError):
        images.save_image(b"GIF8" + b"0" * (4 * 1024 * 1024))
    with pytest.raises(images.ImageError):
        images.save_image(b"<svg>")
    assert images.image_file("../" + name) is None and images.image_file("x/" + name) is None


def test_clean_pairs_loai_ve_phai_trung():
    from ai.quiz_gen import clean_pairs

    assert clean_pairs([["Chuột", "Vào"], ["Loa", "Vào"], ["Loa", "Ra"]]) == [["Chuột", "Vào"], ["Loa", "Ra"]]
