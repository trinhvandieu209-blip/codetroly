"""Gợi ý từng bước cho học sinh làm sai, không tiết lộ đáp án."""
from typing import Any

from ai import prompts
from ai.grader import normalize_text
from ai.provider import AIError, get_provider

MCQ_HINTS = {
    1: "Em đọc lại thật kỹ câu hỏi, gạch chân từ quan trọng rồi nhớ xem mục \"{topic}\" trong sách nói gì nhé.",
    2: "Em thử loại bỏ lựa chọn nào không liên quan gì tới mục \"{topic}\". Lựa chọn em đã chọn có thật sự trả lời đúng câu hỏi không?",
    3: "Mở sách, tìm mục \"{topic}\" và đọc lại phần chữ in đậm trong khung ghi nhớ. Câu trả lời nằm ngay trong đó, em so với từng lựa chọn nhé.",
}
SHORT_HINTS = {
    1: "Em đọc lại câu hỏi và nhớ xem mục \"{topic}\" trong sách nói gì nhé.",
    2: "Câu trả lời gồm {n_words} từ. Em thử nhớ lại khung ghi nhớ của mục \"{topic}\".",
    3: "Câu trả lời gồm {n_words} từ, bắt đầu bằng chữ \"{first}\". Em mở mục \"{topic}\" trong sách để kiểm tra nhé.",
}


MATCH_HINTS = {
    1: "Em đọc kỹ từng vế trái rồi nghĩ xem nó thuộc mục \"{topic}\" nói về điều gì, sau đó mới tìm vế phải phù hợp.",
    2: "Em thử nối cặp nào chắc chắn nhất trước, rồi loại dần các vế phải còn lại.",
    3: "Mở sách mục \"{topic}\", mỗi khái niệm ở vế trái đều có một câu giải thích ngắn, so với vế phải nhé.",
}


def hint_offline(question: dict[str, Any], level: int) -> str:
    """Gợi ý soạn sẵn theo mức độ, không dùng phần giải thích để tránh lộ đáp án."""
    level = max(1, min(3, level))
    topic = question.get("topic") or "bài học"
    if question.get("qtype") == "match":
        return MATCH_HINTS[level].format(topic=topic)
    if question.get("qtype") == "short":
        answer = str(question.get("answer", "")).strip()
        words = answer.split()
        if level == 3 and len(words) < 3:
            level = 2
        return SHORT_HINTS[level].format(topic=topic, n_words=len(words), first=(words[0][0].upper() if words else "?"))
    return MCQ_HINTS[level].format(topic=topic)


def leaks_answer(question: dict[str, Any], hint: str) -> bool:
    """Gợi ý bị coi là lộ đáp án nếu chứa nội dung lựa chọn đúng hoặc đáp án câu ngắn."""
    h = normalize_text(hint)
    answer = str(question.get("answer", "")).strip()
    if question.get("qtype") == "match":
        return any(
            normalize_text(p[0]) in h and normalize_text(p[1]) in h for p in question.get("options", []) if len(p) == 2
        )
    if question.get("qtype") == "mcq":
        correct = next((o for o in question.get("options", []) if o[:1].upper() == answer[:1].upper()), "")
        body = normalize_text(correct[2:]) if correct else ""
        return (len(body) >= 3 and body in h) or f"dap an {answer.lower()}" in h or f"chon {answer.lower()}" in h
    a = normalize_text(answer)
    return len(a) >= 2 and a in h


def make_hint(question: dict[str, Any], given: str, level: int, grade: str) -> str:
    """Tạo gợi ý bằng AI, lỗi thì dùng gợi ý soạn sẵn."""
    provider = get_provider()
    if provider is None:
        return hint_offline(question, level)
    options_block = ""
    if question.get("qtype") == "match":
        lefts = ", ".join(p[0] for p in question["options"])
        rights = ", ".join(sorted((p[1] for p in question["options"]), key=str.lower))
        options_block = f"Vế trái: {lefts}. Vế phải (đã xáo): {rights}. KHÔNG được nói cặp nào đi với cặp nào.\n"
    elif question.get("options"):
        options_block = "Các lựa chọn: " + " | ".join(question["options"]) + "\n"
    prompt = prompts.HINT.format(
        safety=prompts.SAFETY_RULES,
        grade=grade,
        prompt=question["prompt"],
        options_block=options_block,
        answer=question["answer"],
        explanation=question.get("explanation", ""),
        given=given or "(bỏ trống)",
        level=level,
    )
    try:
        result = provider.generate_json(prompt, fast=True)
        hint = str(result.get("hint", "")).strip()
        if not hint or leaks_answer(question, hint):
            return hint_offline(question, level)
        return hint
    except AIError:
        return hint_offline(question, level)
