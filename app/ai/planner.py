"""Lập kế hoạch ôn tập cá nhân sau mỗi bài làm."""
from ai import prompts
from ai.provider import AIError, get_provider


def plan_offline(name: str, score: int, total: int, weak: list[str], strong: list[str]) -> str:
    """Kế hoạch soạn sẵn khi không có AI."""
    lines = [f"Em {name} làm đúng {score}/{total} câu."]
    if strong:
        lines.append("Em nắm tốt: " + ", ".join(strong) + ". Giỏi lắm!")
    if not weak:
        lines.append("Em đã nắm chắc bài, hãy làm thêm bài luyện tập trong vở bài tập nhé.")
        return "\n".join(lines)
    lines.append("Kế hoạch 3 ngày tới, mỗi ngày 10-15 phút:")
    for day, topic in enumerate(weak[:3], start=1):
        lines.append(f"- Ngày {day}: đọc lại mục \"{topic}\" trong sách, kể lại cho bố mẹ nghe 2 ý chính.")
    lines.append("- Sau đó vào làm lại bài này để xem em tiến bộ bao nhiêu.")
    return "\n".join(lines)


def make_plan(name: str, grade: str, title: str, score: int, total: int, weak: list[str], strong: list[str]) -> str:
    """Tạo kế hoạch bằng AI, lỗi thì dùng bản soạn sẵn."""
    provider = get_provider()
    if provider is None:
        return plan_offline(name, score, total, weak, strong)
    prompt = prompts.STUDY_PLAN.format(
        safety=prompts.SAFETY_RULES,
        grade=grade,
        title=title,
        score=score,
        total=total,
        weak_topics=", ".join(weak) or "(không có)",
        strong_topics=", ".join(strong) or "(không có)",
    )
    try:
        result = provider.generate_json(prompt, fast=True)
        plan = str(result.get("plan", "")).strip()
        return plan or plan_offline(name, score, total, weak, strong)
    except AIError:
        return plan_offline(name, score, total, weak, strong)
