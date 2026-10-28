"""Sinh bộ câu hỏi từ tài liệu bài học."""
import json
import logging
import re
from typing import Any

from ai import prompts
from ai.provider import AIError, Attachment, get_provider
from config import SEED_PATH

VALID_TYPES = {"mcq", "short", "match"}
MATCH_ALIASES = {"match", "matching", "pair", "pairs", "noi", "noi_ghep", "noighep"}
PAIR_KEYS = ("pairs", "options", "matches", "cap", "cap_noi")
LEFT_KEYS = ("left", "trai", "ve_trai", "a", "key", "term", "khai_niem", "question")
RIGHT_KEYS = ("right", "phai", "ve_phai", "b", "value", "definition", "mo_ta", "answer")
PAIR_SEPARATORS = (" - ", " – ", " — ", " = ", ": ", " → ", " -> ", " | ")
MAX_PAIRS = 5
MIN_VALID_QUESTIONS = 1
log = logging.getLogger(__name__)


def _validate_question(raw: dict[str, Any], position: int) -> dict[str, Any]:
    """Chuẩn hóa một câu hỏi do AI trả về, ném AIError nếu thiếu trường."""
    qtype = str(raw.get("qtype", "")).strip().lower().replace("-", "_").replace(" ", "_")
    prompt = str(raw.get("prompt", "")).strip()
    answer = str(raw.get("answer", "")).strip()
    if qtype in MATCH_ALIASES:
        return _validate_match(raw, position, prompt)
    if qtype not in VALID_TYPES or not prompt or not answer:
        raise AIError(f"Câu {position} thiếu dữ liệu")
    options = [str(o).strip() for o in raw.get("options", []) if str(o).strip()]
    if qtype == "mcq":
        if len(options) < 2:
            raise AIError(f"Câu {position} thiếu lựa chọn")
        options = _relabel_options(options)
        answer = _answer_letter(options, answer)
        if answer is None:
            raise AIError(f"Câu {position} đáp án không khớp lựa chọn")
    if qtype == "short":
        options = word_bank(raw, answer)
    return {
        "position": position,
        "qtype": qtype,
        "prompt": prompt,
        "options": options,
        "answer": answer,
        "explanation": str(raw.get("explanation", "")).strip(),
        "topic": str(raw.get("topic", "")).strip(),
    }


def word_bank(raw: dict[str, Any], answer: str) -> list[str]:
    """Ô từ gợi ý cho câu ngắn: luôn chứa đáp án, tối đa 5 từ, xáo thứ tự ổn định theo chữ cái."""
    words = [str(w).strip() for w in raw.get("word_bank", []) if str(w).strip()]
    if not words:
        return []
    if answer.lower() not in [w.lower() for w in words]:
        words.insert(0, answer)
    return sorted(dict.fromkeys(words[:5]), key=str.lower)


def _pair_from_item(item: Any) -> tuple[str, str] | None:
    """Một cặp có thể là [trái, phải], {"left":..,"right":..} hoặc chuỗi "trái - phải"."""
    if isinstance(item, dict):
        left = next((item[k] for k in LEFT_KEYS if item.get(k)), None)
        right = next((item[k] for k in RIGHT_KEYS if item.get(k)), None)
        if left is None or right is None:
            vals = [v for v in item.values() if str(v).strip()]
            left, right = (vals[0], vals[1]) if len(vals) >= 2 else (None, None)
        return (str(left), str(right)) if left is not None and right is not None else None
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        return str(item[0]), str(item[1])
    if isinstance(item, str):
        for sep in PAIR_SEPARATORS:
            if sep in item:
                left, right = item.split(sep, 1)
                return left, right
    return None


def _as_pair_list(raw: Any) -> list[Any]:
    """AI đôi khi trả cặp nối dạng từ điển {"vế trái": "vế phải"}; quy về danh sách."""
    if isinstance(raw, dict):
        return [[k, v] for k, v in raw.items()]
    return raw if isinstance(raw, list) else []


def clean_pairs(raw_pairs: Any) -> list[list[str]]:
    """Chuẩn hóa cặp nối: nhận list/dict/chuỗi, bỏ cặp thiếu vế, bỏ trùng, tối đa 5 cặp."""
    pairs: list[list[str]] = []
    seen_left: set[str] = set()
    seen_right: set[str] = set()
    for item in raw_pairs if isinstance(raw_pairs, list) else []:
        parsed = _pair_from_item(item)
        if parsed is None:
            continue
        left = re.sub(r"^[A-Za-z0-9][.)]\s*", "", parsed[0]).strip()
        right = re.sub(r"^[A-Za-z0-9][.)]\s*", "", parsed[1]).strip()
        if left and right and left.lower() not in seen_left and right.lower() not in seen_right:
            seen_left.add(left.lower())
            seen_right.add(right.lower())
            pairs.append([left[:80], right[:120]])
    return pairs[:MAX_PAIRS]


def _validate_match(raw: dict[str, Any], position: int, prompt: str) -> dict[str, Any]:
    pairs = next((clean_pairs(_as_pair_list(raw.get(k))) for k in PAIR_KEYS if raw.get(k)), [])
    if not prompt or len(pairs) < 2:
        raise AIError(f"Câu {position} nối ghép thiếu cặp")
    return {
        "position": position,
        "qtype": "match",
        "prompt": prompt,
        "options": pairs,
        "answer": "",
        "explanation": str(raw.get("explanation", "")).strip(),
        "topic": str(raw.get("topic", "")).strip(),
    }


def _answer_letter(options: list[str], answer: str) -> str | None:
    """Đáp án có thể là 'B', 'B.', 'B. Chuột' hoặc chỉ 'Chuột': quy về chữ cái của lựa chọn khớp."""
    a = answer.strip()
    if re.fullmatch(r"[A-Za-z][.)]?", a) and a[:1].upper() in [o[0] for o in options]:
        return a[:1].upper()
    body = re.sub(r"^[A-Za-z0-9][.)]\s*", "", a).strip().lower()
    for o in options:
        if o[3:].strip().lower() == body:
            return o[0]
    return None


def _relabel_options(options: list[str]) -> list[str]:
    """Ép mọi lựa chọn về dạng 'A. ...', 'B. ...' để chữ cái đáp án luôn duy nhất."""
    result = []
    for i, opt in enumerate(options):
        letter = chr(ord("A") + i)
        body = re.sub(r"^[A-Za-z0-9][.)]\s*", "", opt).strip()
        result.append(f"{letter}. {body}")
    return result


def normalize_quiz(payload: dict[str, Any], fallback_title: str) -> dict[str, Any]:
    """Chuyển JSON của AI thành cấu trúc quiz đã kiểm tra."""
    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise AIError("AI không trả về câu hỏi nào")
    questions: list[dict[str, Any]] = []
    for raw in raw_questions:
        try:
            questions.append(_validate_question(raw if isinstance(raw, dict) else {}, len(questions) + 1))
        except AIError as exc:
            log.warning("Bỏ câu AI trả sai định dạng: %s", exc)
    if len(questions) < MIN_VALID_QUESTIONS:
        raise AIError("AI trả về câu hỏi sai định dạng, hãy thử lại")
    title = str(payload.get("title") or fallback_title).strip()
    return {"title": title, "questions": questions}


def load_seed_quiz(key: str, grade: str = "") -> dict[str, Any]:
    """Lấy bộ câu hỏi mẫu soạn sẵn (dùng khi chưa có khóa AI); ưu tiên bộ đúng khối lớp."""
    with open(SEED_PATH, encoding="utf-8") as fh:
        seeds = json.load(fh)
    candidates = [f"{key}_lop{grade}", key if grade in ("", "3") else "", f"lop{grade}"]
    chosen = next((c for c in candidates if c and c in seeds), next(iter(seeds)))
    return normalize_quiz(seeds[chosen], seeds[chosen].get("title", chosen))


def generate_quiz(
    attachment: Attachment, grade: str, n_questions: int, fallback_title: str, seed_key: str = ""
) -> tuple[dict[str, Any], str]:
    """Sinh quiz bằng AI; nếu chưa có khóa thì dùng bộ mẫu. Trả về (quiz, nguồn)."""
    provider = get_provider()
    if provider is None:
        return load_seed_quiz(seed_key, grade), "mau"
    n_short = max(1, n_questions // 4)
    n_match = 1 if n_questions >= 6 else 0
    prompt = prompts.QUIZ_GENERATION.format(
        safety=prompts.SAFETY_RULES,
        n=n_questions,
        n_mcq=n_questions - n_short - n_match,
        n_short=n_short,
        n_match=n_match,
        grade=grade,
    )
    payload = provider.generate_json(prompt, attachment)
    return normalize_quiz(payload, fallback_title), "ai"
