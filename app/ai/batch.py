"""Chấm cả bài và lập kế hoạch ôn tập trong một lượt gọi AI, tiết kiệm hạn mức gói miễn phí."""
from typing import Any

from ai import prompts
from ai.grader import grade_match_result, grade_mcq_result, offline_short_result
from ai.planner import plan_offline
from ai.provider import AIError, get_provider

Graded = list[tuple[dict[str, Any], str, bool, str]]


def _unique(items: list[str]) -> list[str]:
    seen: list[str] = []
    for it in items:
        if it not in seen:
            seen.append(it)
    return seen


def _short_block(shorts: list[tuple[dict[str, Any], str]]) -> str:
    lines = []
    for q, given in shorts:
        safe = given[:200].replace("</tra_loi>", "")
        lines.append(f'- id {q["id"]}: Câu hỏi: {q["prompt"]} | Đáp án mẫu: {q["answer"]} | <tra_loi>{safe}</tra_loi>')
    return "\n".join(lines) if lines else "(không có câu trả lời ngắn)"


def _merge(shorts: list[tuple[dict[str, Any], str]], grades: Any) -> dict[int, tuple[bool, str]]:
    """Ghép kết quả AI theo id; câu nào AI bỏ sót thì chấm ngoại tuyến."""
    by_id: dict[int, tuple[bool, str]] = {}
    for item in grades if isinstance(grades, list) else []:
        try:
            by_id[int(item.get("id"))] = (bool(item.get("correct")), str(item.get("feedback", "")).strip())
        except (TypeError, ValueError, AttributeError):
            continue
    result = {}
    for q, given in shorts:
        ok_fb = by_id.get(q["id"])
        result[q["id"]] = ok_fb if ok_fb and ok_fb[1] else offline_short_result(q, given)
    return result


def grade_and_plan(quiz: dict[str, Any], student_name: str, given: dict[int, str], use_ai: bool = True) -> tuple[Graded, str]:
    """Trả về danh sách (câu, trả lời, đúng/sai, nhận xét) và kế hoạch ôn tập."""
    mcq = [(q, given.get(q["id"], "")) for q in quiz["questions"] if q["qtype"] in ("mcq", "match")]
    shorts = [(q, given.get(q["id"], "")) for q in quiz["questions"] if q["qtype"] == "short"]
    mcq_results = {
        q["id"]: (grade_match_result(q, g) if q["qtype"] == "match" else grade_mcq_result(q, g)) for q, g in mcq
    }
    weak = _unique([q["topic"] for q, _ in mcq if not mcq_results[q["id"]][0] and q["topic"]])
    strong = _unique([q["topic"] for q, _ in mcq if mcq_results[q["id"]][0] and q["topic"]])
    short_results, plan = _ask_ai(quiz, mcq, mcq_results, shorts, weak, strong) if use_ai else (None, "")
    if short_results is None:
        short_results = {q["id"]: offline_short_result(q, g) for q, g in shorts}
    graded: Graded = []
    for q in quiz["questions"]:
        g = given.get(q["id"], "")
        ok, fb = mcq_results[q["id"]] if q["qtype"] in ("mcq", "match") else short_results[q["id"]]
        graded.append((q, g, ok, fb))
    if not plan:
        score = sum(1 for _, _, ok, _ in graded if ok)
        weak_all = _unique([q["topic"] for q, _, ok, _ in graded if not ok and q["topic"]])
        strong_all = _unique([q["topic"] for q, _, ok, _ in graded if ok and q["topic"]])
        plan = plan_offline(student_name, score, len(graded), weak_all, strong_all)
    return graded, plan


def _ask_ai(quiz, mcq, mcq_results, shorts, weak, strong) -> tuple[dict[int, tuple[bool, str]] | None, str]:
    provider = get_provider()
    if provider is None:
        return None, ""
    prompt = prompts.GRADE_AND_PLAN.format(
        safety=prompts.SAFETY_RULES,
        grade=quiz["grade"],
        title=quiz["title"],
        short_block=_short_block(shorts),
        mcq_right=sum(1 for q, _ in mcq if mcq_results[q["id"]][0]),
        mcq_total=len(mcq),
        weak_topics=", ".join(weak) or "(không có)",
        strong_topics=", ".join(strong) or "(không có)",
    )
    try:
        result = provider.generate_json(prompt, fast=True)
    except AIError:
        return None, ""
    return _merge(shorts, result.get("grades")), str(result.get("plan", "")).strip()
