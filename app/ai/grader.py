"""Chấm điểm câu trả lời của học sinh."""
import re
import unicodedata
from typing import Any

from ai import prompts
from ai.provider import AIError, get_provider


def normalize_text(text: str) -> str:
    """Bỏ dấu, chữ thường, bỏ ký tự thừa để so khớp mềm."""
    nfkd = unicodedata.normalize("NFD", text.lower())
    no_accent = "".join(ch for ch in nfkd if unicodedata.category(ch) != "Mn")
    no_accent = no_accent.replace("đ", "d")
    return re.sub(r"[^a-z0-9 ]+", " ", no_accent).strip()


def grade_mcq(answer: str, given: str) -> bool:
    """Chấm trắc nghiệm: so chữ cái đầu."""
    return bool(given) and given.strip()[0].upper() == answer.strip()[0].upper()


def grade_short_offline(answer: str, given: str) -> bool:
    """Chấm câu ngắn không cần AI: khớp chuỗi đã chuẩn hóa hoặc chứa từ khóa chính."""
    a, g = normalize_text(answer), normalize_text(given)
    if not g or len(g.split()) > 2 * max(1, len(a.split())) + 1:
        return False
    if a == g or (len(g) >= 3 and a in g):
        return True
    a_words = {w for w in a.split() if len(w) >= 2}
    g_words = set(g.split())
    return bool(a_words) and len(a_words & g_words) / len(a_words) >= 0.6


def grade_short(question: dict[str, Any], given: str, grade: str) -> tuple[bool, str]:
    """Chấm câu ngắn: ưu tiên AI, lỗi hoặc không có khóa thì chấm ngoại tuyến."""
    provider = get_provider()
    if provider is not None:
        prompt = prompts.SHORT_ANSWER_GRADING.format(
            safety=prompts.SAFETY_RULES,
            grade=grade,
            prompt=question["prompt"],
            answer=question["answer"],
            given=given[:200].replace("</tra_loi>", ""),
        )
        try:
            result = provider.generate_json(prompt, fast=True)
            return bool(result.get("correct")), str(result.get("feedback", "")).strip()
        except AIError:
            pass
    correct = grade_short_offline(question["answer"], given)
    feedback = "Đúng rồi, em giỏi lắm!" if correct else f"Chưa đúng. Em xem lại mục \"{question['topic']}\" nhé."
    return correct, feedback


def offline_short_result(question: dict[str, Any], given: str) -> tuple[bool, str]:
    """Kết quả chấm câu ngắn không cần AI, kèm nhận xét."""
    correct = grade_short_offline(question["answer"], given)
    feedback = "Đúng rồi, em giỏi lắm!" if correct else f"Chưa đúng. Em xem lại mục \"{question['topic']}\" nhé."
    return correct, feedback


def grade_mcq_result(question: dict[str, Any], given: str) -> tuple[bool, str]:
    """Kết quả chấm trắc nghiệm kèm nhận xét."""
    correct = grade_mcq(question["answer"], given)
    feedback = "Chính xác!" if correct else "Chưa đúng, em bấm 'Gợi ý' để trợ lý AI giúp nhé."
    return correct, feedback


def parse_match(given: str) -> dict[int, int]:
    """'0:2,1:0' -> {0: 2, 1: 0} (chỉ số vế trái -> chỉ số vế phải gốc)."""
    result: dict[int, int] = {}
    for part in (given or "").split(","):
        if ":" in part:
            left, right = part.split(":", 1)
            try:
                result[int(left)] = int(right)
            except ValueError:
                continue
    return result


def grade_match_result(question: dict[str, Any], given: str) -> tuple[bool, str]:
    """Đúng khi mọi cặp đều nối đúng; nhận xét nêu số cặp đúng."""
    pairs = question.get("options") or []
    chosen = parse_match(given)
    right = sum(1 for i in range(len(pairs)) if chosen.get(i) == i)
    correct = right == len(pairs) and len(pairs) > 0
    feedback = "Nối đúng tất cả, giỏi lắm!" if correct else f"Em nối đúng {right}/{len(pairs)} cặp, bấm 'Gợi ý' để xem lại nhé."
    return correct, feedback


def grade_answer(question: dict[str, Any], given: str, grade: str) -> tuple[bool, str]:
    """Chấm một câu bất kỳ, trả về (đúng/sai, nhận xét)."""
    given = (given or "").strip()
    if question["qtype"] == "match":
        return grade_match_result(question, given)
    if question["qtype"] == "mcq":
        correct = grade_mcq(question["answer"], given)
        feedback = "Chính xác!" if correct else "Chưa đúng, em bấm 'Gợi ý' để trợ lý AI giúp nhé."
        return correct, feedback
    return grade_short(question, given, grade)
