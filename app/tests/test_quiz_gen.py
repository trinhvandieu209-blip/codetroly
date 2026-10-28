"""Kiểm tra chuẩn hóa câu hỏi AI trả về, nhất là câu nối ghép nhiều định dạng."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai.provider import AIError  # noqa: E402
from ai.quiz_gen import clean_pairs, normalize_quiz  # noqa: E402

MCQ = {"qtype": "mcq", "prompt": "Câu hỏi?", "options": ["A. x", "B. y", "C. z"], "answer": "A", "explanation": "", "topic": "t"}


def test_clean_pairs_nhan_dict_va_chuoi():
    pairs = clean_pairs([
        {"left": "Màn hình", "right": "Hiển thị"},
        {"trai": "Chuột", "phai": "Điều khiển"},
        "Bàn phím - Nhập chữ",
        "Loa: Phát âm thanh",
    ])
    assert pairs == [["Màn hình", "Hiển thị"], ["Chuột", "Điều khiển"], ["Bàn phím", "Nhập chữ"], ["Loa", "Phát âm thanh"]]


def test_cau_noi_dung_khoa_options_va_qtype_khac_ten():
    raw = {"qtype": "matching", "prompt": "Nối", "options": [["a", "1"], ["b", "2"], ["c", "3"]], "answer": "", "topic": "t"}
    quiz = normalize_quiz({"questions": [MCQ, raw]}, "Đề")
    assert quiz["questions"][1]["qtype"] == "match"
    assert quiz["questions"][1]["options"] == [["a", "1"], ["b", "2"], ["c", "3"]]


def test_cau_loi_bi_bo_khong_hong_ca_de():
    hong = {"qtype": "match", "prompt": "Nối", "pairs": "không phải danh sách"}
    quiz = normalize_quiz({"questions": [MCQ, hong, dict(MCQ, prompt="Câu 3?")]}, "Đề")
    assert [q["position"] for q in quiz["questions"]] == [1, 2]
    assert all(q["qtype"] == "mcq" for q in quiz["questions"])


def test_tat_ca_cau_loi_thi_bao_loi():
    with pytest.raises(AIError):
        normalize_quiz({"questions": [{"qtype": "mcq", "prompt": "", "options": [], "answer": ""}]}, "Đề")


def test_cau_noi_dang_tu_dien():
    raw = {"qtype": "match", "prompt": "Nối", "pairs": {"Màn hình": "Hiển thị", "Chuột": "Điều khiển"}}
    quiz = normalize_quiz({"questions": [raw]}, "Đề")
    assert quiz["questions"][0]["options"] == [["Màn hình", "Hiển thị"], ["Chuột", "Điều khiển"]]


def test_word_ve_phai_khong_giu_thu_tu_goc():
    from services.export_docx import _shuffled_right

    for qid in range(1, 60):
        q = {"id": qid, "options": [["a", "1"], ["b", "2"], ["c", "3"], ["d", "4"]]}
        assert [t for _, t in _shuffled_right(q)] != ["1", "2", "3", "4"]
