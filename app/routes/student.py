"""Khu vực học sinh: nhập mã, làm bài, xem kết quả, xin gợi ý."""
import re

from fastapi import APIRouter, Form, Request
from fastapi.concurrency import run_in_threadpool
import secrets

from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from ai.grader import normalize_text
from routes.common import client_ip, render, set_flash
from config import HINT_RATE_LIMIT_PER_MINUTE
from ai.grader import grade_answer, grade_short_offline
from services import attempts, games, images, quizzes, ratelimit

router = APIRouter()
NAME_RE = re.compile(r"^[\w\sÀ-ỹ'.-]{2,40}$", re.UNICODE)


def ten_hop_le(name: str) -> bool:
    """Tên gọi phải có chữ cái và ít nhất một nguyên âm, để loại tên gõ bừa như 'dfs'."""
    if not NAME_RE.match(name):
        return False
    plain = normalize_text(name)
    return any(ch.isalpha() for ch in plain) and any(v in plain for v in "aeiouy")
MAX_ANSWER_LEN = 200


@router.get("/")
def home(request: Request):
    return render(request, "hs_home.html")


@router.get("/gioi-thieu")
def product_intro(request: Request):
    """Trang giới thiệu sản phẩm công khai: chức năng, quy trình, an toàn, kết quả thử nghiệm."""
    return render(request, "gioi_thieu.html")


@router.get("/huong-dan")
def guide(request: Request):
    """Hướng dẫn làm bài và quy tắc dùng AI an toàn, có trách nhiệm cho học sinh."""
    return render(request, "hs_huong_dan.html")


def _too_fast(request: Request) -> bool:
    return not ratelimit.allow("hs:" + client_ip(request))


@router.get("/thoat")
def student_logout(request: Request):
    """Học sinh bấm Thoát trên máy dùng chung để em sau không thấy bài của mình."""
    request.session.clear()
    set_flash(request, "Em đã thoát. Bạn tiếp theo nhập mã bài và tên của mình nhé.")
    return RedirectResponse("/", status_code=303)


@router.post("/vao-bai")
def enter(request: Request, code: str = Form(""), name: str = Form("")):
    if _too_fast(request):
        set_flash(request, "Em thao tác hơi nhanh, chờ một chút rồi thử lại nhé", "warn")
        return RedirectResponse("/", status_code=303)
    quiz = quizzes.get_quiz_by_code(code)
    name = name.strip()
    if quiz is None:
        set_flash(request, "Mã bài không đúng hoặc bài chưa được phát hành", "warn")
        return RedirectResponse("/", status_code=303)
    if not ten_hop_le(name):
        set_flash(request, "Em nhập tên thật và lớp của em, ví dụ: Minh 4.3", "warn")
        return RedirectResponse("/", status_code=303)
    students = dict(request.session.get("students") or {})
    students[str(quiz["id"])] = name
    request.session["students"] = students
    submitted = dict(request.session.get("submitted") or {})
    submitted.pop(str(quiz["id"]), None)
    request.session["submitted"] = submitted
    return RedirectResponse(f"/lam-bai/{quiz['code']}", status_code=303)


def _current_student(request: Request, code: str):
    """Học sinh có thể mở nhiều bài trong cùng phiên; mỗi bài nhớ tên riêng."""
    quiz = quizzes.get_quiz_by_code(code)
    if quiz is None:
        return None, None
    name = (request.session.get("students") or {}).get(str(quiz["id"]))
    if not name:
        return None, None
    return {"name": name, "quiz_id": quiz["id"]}, quiz


@router.get("/lam-bai/{code}")
def take(request: Request, code: str):
    student, quiz = _current_student(request, code)
    if quiz is None:
        set_flash(request, "Em hãy nhập mã bài và tên trước nhé", "warn")
        return RedirectResponse("/", status_code=303)
    sid = _sid(request)
    match_views = {q["id"]: games.match_view(sid, q) for q in quiz["questions"] if q["qtype"] == "match"}
    return render(request, "hs_lam_bai.html", quiz=quiz, student=student, match_views=match_views)


@router.post("/lam-bai/{code}")
async def submit(request: Request, code: str):
    student, quiz = _current_student(request, code)
    if quiz is None:
        set_flash(request, "Bài này thầy cô đã đóng hoặc phiên của em đã hết. Em hỏi thầy cô mã bài mới nhé.", "warn")
        return RedirectResponse("/", status_code=303)
    if _too_fast(request):
        set_flash(request, "Em thao tác hơi nhanh, chờ một chút rồi nộp lại nhé", "warn")
        return RedirectResponse(f"/lam-bai/{code}", status_code=303)
    submitted = dict(request.session.get("submitted") or {})
    if str(quiz["id"]) in submitted:
        return RedirectResponse(f"/ket-qua/{submitted[str(quiz['id'])]}", status_code=303)
    form = await request.form()
    given = {q["id"]: str(form.get(f"q_{q['id']}", "")).strip()[:MAX_ANSWER_LEN] for q in quiz["questions"]}
    given = games.decode_all(_sid(request), quiz, given)
    attempt_id = await run_in_threadpool(attempts.submit_attempt, quiz, student["name"], given)
    owned = list(request.session.get("attempt_ids") or [])
    request.session["attempt_ids"] = (owned + [attempt_id])[-20:]
    submitted[str(quiz["id"])] = attempt_id
    request.session["submitted"] = submitted
    return RedirectResponse(f"/ket-qua/{attempt_id}", status_code=303)


def _owns_attempt(request: Request, attempt_id: int) -> bool:
    return attempt_id in (request.session.get("attempt_ids") or []) or bool(request.session.get("teacher"))


@router.get("/ket-qua/{attempt_id}")
def result(request: Request, attempt_id: int):
    if not _owns_attempt(request, attempt_id):
        return RedirectResponse("/", status_code=303)
    attempt = attempts.get_attempt(attempt_id)
    if attempt is None:
        return RedirectResponse("/", status_code=303)
    return render(request, "hs_ket_qua.html", attempt=attempt, teacher_view=False, feedback=attempts.get_feedback(attempt_id))


@router.post("/phan-hoi/{attempt_id}")
def feedback(request: Request, attempt_id: int, rating: str = Form(""), comment: str = Form("")):
    if request.session.get("teacher") or not _owns_attempt(request, attempt_id) or attempts.get_attempt(attempt_id) is None:
        return RedirectResponse("/", status_code=303)
    if rating not in ("1", "2", "3"):
        set_flash(request, "Em chọn một gương mặt trước nhé", "warn")
        return RedirectResponse(f"/ket-qua/{attempt_id}#phan-hoi", status_code=303)
    attempts.save_feedback(attempt_id, int(rating), comment)
    set_flash(request, "Cảm ơn em đã chia sẻ!")
    return RedirectResponse(f"/ket-qua/{attempt_id}#phan-hoi", status_code=303)


@router.get("/anh/{name}")
def question_image(name: str):
    """Ảnh câu hỏi; chỉ phục vụ tệp trong thư mục ảnh."""
    path = images.image_file(name)
    if path is None:
        return RedirectResponse("/", status_code=303)
    return FileResponse(path)


GAME_SECONDS_PER_QUESTION = 20
GAME_BASE_POINTS = 100
GAME_TIME_BONUS_MAX = 50
GAME_STREAK_BONUS = 10


def game_points(correct: bool, elapsed: float, streak: int) -> int:
    """Điểm một câu: đúng 100, cộng tới 50 nếu nhanh, cộng 10 mỗi câu trong chuỗi đúng."""
    if not correct:
        return 0
    quick = max(0.0, 1 - min(elapsed, GAME_SECONDS_PER_QUESTION) / GAME_SECONDS_PER_QUESTION)
    return GAME_BASE_POINTS + int(GAME_TIME_BONUS_MAX * quick) + GAME_STREAK_BONUS * min(streak, 10)


def _sid(request: Request) -> str:
    """Mã phiên ngẫu nhiên để lưu hoán vị nối ghép trên server (cookie chỉ giữ mã này)."""
    sid = request.session.get("sid")
    if not sid:
        sid = secrets.token_urlsafe(12)
        request.session["sid"] = sid
    return sid


def _public_questions(sid: str, quiz: dict) -> list[dict]:
    """Dữ liệu câu hỏi gửi xuống game, KHÔNG kèm đáp án; vế phải nối ghép dùng token ngẫu nhiên."""
    out = []
    for q in quiz["questions"]:
        item = {"id": q["id"], "qtype": q["qtype"], "prompt": q["prompt"], "image": q.get("image_path", "")}
        if q["qtype"] == "mcq":
            item["options"] = q["options"]
        elif q["qtype"] == "match":
            item["left"] = [p[0] for p in q["options"]]
            item["right"] = [[tok, text] for tok, text in games.match_view(sid, q)]
        else:
            item["bank"] = q["options"]
        out.append(item)
    return out


@router.get("/game/{code}")
def game(request: Request, code: str):
    student, quiz = _current_student(request, code)
    if quiz is None:
        set_flash(request, "Em hãy nhập mã bài và tên trước nhé", "warn")
        return RedirectResponse("/", status_code=303)
    if not ratelimit.allow("game:" + client_ip(request), 30):
        set_flash(request, "Em chơi hơi nhanh, nghỉ một chút nhé", "warn")
        return RedirectResponse(f"/lam-bai/{code}", status_code=303)
    request.session["game_token"] = games.start(quiz["id"], student["name"])
    return render(
        request, "hs_game.html", quiz=quiz, student=student,
        questions=_public_questions(_sid(request), quiz), seconds=GAME_SECONDS_PER_QUESTION,
    )


def _game_context(request: Request, code: str):
    student, quiz = _current_student(request, code)
    game_row = games.get(request.session.get("game_token") or "")
    if quiz is None or game_row is None or game_row["quiz_id"] != quiz["id"]:
        return None, None, None
    return student, quiz, game_row


@router.post("/game/{code}/bat-dau/{question_id}")
def game_show(request: Request, code: str, question_id: int):
    """Trình duyệt báo câu hỏi vừa hiện; server bắt đầu bấm giờ cho câu đó."""
    _, quiz, game_row = _game_context(request, code)
    if quiz is None:
        return JSONResponse({"error": "Phiên game không hợp lệ"}, status_code=400)
    games.mark_asked(game_row["id"], question_id)
    return JSONResponse({"ok": True})


@router.post("/game/{code}/tra-loi")
async def game_answer(request: Request, code: str):
    _, quiz, game_row = _game_context(request, code)
    if quiz is None:
        return JSONResponse({"error": "Phiên game không hợp lệ"}, status_code=400)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise TypeError("body")
        qid = int(body.get("question_id", 0))
    except (ValueError, TypeError):
        return JSONResponse({"error": "Dữ liệu không hợp lệ"}, status_code=400)
    question = next((q for q in quiz["questions"] if q["id"] == qid), None)
    if question is None:
        return JSONResponse({"error": "Câu hỏi không tồn tại"}, status_code=404)
    given = str(body.get("given", ""))[:MAX_ANSWER_LEN]
    if question["qtype"] == "match":
        given = games.match_decode(_sid(request), question, given)
    if question["qtype"] == "short":
        correct = grade_short_offline(question["answer"], given)  # trong game chấm tức thì, không chờ AI
    else:
        correct, _ = grade_answer(question, given, quiz["grade"])
    result = games.record_answer(game_row["id"], qid, given, correct, lambda el, st: game_points(True, el, st))
    if result is None:
        return JSONResponse({"error": "Câu này em đã trả lời rồi"}, status_code=409)
    reveal = question["answer"]
    if question["qtype"] == "match":
        reveal = " | ".join(f"{p[0]} → {p[1]}" for p in question["options"])
    elif question["qtype"] == "mcq":
        reveal = next((o for o in question["options"] if o[:1] == question["answer"]), question["answer"])
    return JSONResponse({"correct": correct, "points": result["points"], "total": result["total"], "streak": result["streak"], "answer": reveal, "explanation": question["explanation"]})


@router.post("/game/{code}/ket-thuc")
async def game_finish(request: Request, code: str):
    student, quiz, game_row = _game_context(request, code)
    if quiz is None:
        return RedirectResponse("/", status_code=303)
    done = games.finish(game_row["token"])
    request.session.pop("game_token", None)
    if done is None:
        return RedirectResponse("/", status_code=303)
    given = {q["id"]: str(done["answers"].get(q["id"], ""))[:MAX_ANSWER_LEN] for q in quiz["questions"]}
    attempt_id = await run_in_threadpool(attempts.create_game_attempt, quiz, student["name"], given)
    attempts.set_game_result(attempt_id, int(done["points"]), int(done["seconds"]))
    owned = list(request.session.get("attempt_ids") or [])
    request.session["attempt_ids"] = (owned + [attempt_id])[-20:]
    return RedirectResponse(f"/bxh/{quiz['code']}?ket_qua={attempt_id}", status_code=303)


@router.get("/bxh/{code}")
def leaderboard_page(request: Request, code: str, ket_qua: int | None = None):
    quiz = quizzes.get_quiz_by_code(code)
    if quiz is None:
        return RedirectResponse("/", status_code=303)
    me = (request.session.get("students") or {}).get(str(quiz["id"]), "")
    return render(request, "hs_bxh.html", quiz=quiz, rows=attempts.leaderboard(quiz["id"]), teacher_view=False, ket_qua=ket_qua, me=me)


@router.post("/goi-y/{attempt_id}/{question_id}")
def hint(request: Request, attempt_id: int, question_id: int):
    if not _owns_attempt(request, attempt_id):
        return JSONResponse({"error": "Không có quyền"}, status_code=403)
    if not ratelimit.allow(f"goi-y:{attempt_id}", HINT_RATE_LIMIT_PER_MINUTE):
        return JSONResponse({"error": "Em bấm hơi nhanh, chờ một chút nhé"}, status_code=429)
    try:
        result = attempts.request_hint(attempt_id, question_id)
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse(result)
