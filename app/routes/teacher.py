"""Khu vực giáo viên: tài liệu, tạo đề, duyệt, phát hành, báo cáo."""
import csv
import hmac
import io
import logging
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, StreamingResponse

from ai.provider import AIError
from ai.quiz_gen import _relabel_options, generate_quiz
from config import DEFAULT_QUESTIONS, MAX_QUESTIONS, MAX_UPLOAD_BYTES, MIN_QUESTIONS, TEACHER_PIN
from routes.common import client_ip, render, set_flash
from ai.quiz_gen import clean_pairs
from services import attempts, export_docx, images, library, materials, quizzes, ratelimit

log = logging.getLogger(__name__)
router = APIRouter(prefix="/gv")
GRADES = ("3", "4", "5")
MAX_OPTIONS = 5
MAX_OPTION_LEN = 200
MAX_TITLE_LEN = 120
STATUS_LABEL = {
    "published": "Đã phát hành, gửi mã cho học sinh",
    "closed": "Đã đóng bài",
    "draft": "Đã chuyển về nháp",
}


def _is_teacher(request: Request) -> bool:
    return bool(request.session.get("teacher"))


def _deny(request: Request) -> RedirectResponse:
    set_flash(request, "Vui lòng nhập mã PIN giáo viên", "warn")
    return RedirectResponse("/gv/dang-nhap", status_code=303)


def _back(request: Request, message: str, url: str = "/gv") -> RedirectResponse:
    set_flash(request, message, "warn")
    return RedirectResponse(url, status_code=303)


@router.get("/dang-nhap")
def login_page(request: Request):
    return render(request, "gv_login.html")


@router.post("/dang-nhap")
def login(request: Request, pin: str = Form("")):
    ip = client_ip(request)
    if ratelimit.pin_locked(ip):
        return _back(request, "Sai PIN quá nhiều lần, vui lòng thử lại sau 5 phút", "/gv/dang-nhap")
    if not hmac.compare_digest(pin.strip().encode(), TEACHER_PIN.encode()):
        ratelimit.record_pin_failure(ip)
        return _back(request, "Mã PIN chưa đúng", "/gv/dang-nhap")
    ratelimit.clear_pin_failures(ip)
    request.session["teacher"] = True
    return RedirectResponse("/gv", status_code=303)


@router.get("/dang-xuat")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@router.get("")
def dashboard(request: Request):
    if not _is_teacher(request):
        return _deny(request)
    return render(
        request,
        "gv_dashboard.html",
        quizzes=quizzes.list_quizzes(),
        materials=materials.list_materials(),
        grades=GRADES,
        lessons={g: library.list_lessons(g) for g in GRADES},
        default_n=DEFAULT_QUESTIONS,
        min_n=MIN_QUESTIONS,
        max_n=MAX_QUESTIONS,
    )


async def _read_upload(file, limit: int) -> bytes:
    """Đọc tệp theo khối, dừng ngay khi vượt giới hạn để không nạp tệp lớn vào RAM."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise materials.MaterialError(f"Tệp quá lớn, tối đa {limit // (1024 * 1024)} MB")
        chunks.append(chunk)


@router.post("/tai-lieu")
async def upload_material(request: Request):
    if not _is_teacher(request):
        return _deny(request)
    declared = int(request.headers.get("content-length") or 0)
    if declared > MAX_UPLOAD_BYTES + 64 * 1024:
        return _back(request, f"Tệp quá lớn, tối đa {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    form = await request.form()
    title, grade, file = str(form.get("title", "")), str(form.get("grade", "")), form.get("file")
    if grade not in GRADES or not title.strip() or file is None or not hasattr(file, "read"):
        return _back(request, "Thiếu tên tài liệu, khối lớp hoặc tệp")
    try:
        data = await _read_upload(file, MAX_UPLOAD_BYTES)
        materials.save_material(title, grade, file.filename or "tai-lieu", data)
    except materials.MaterialError as exc:
        return _back(request, str(exc))
    set_flash(request, "Đã lưu tài liệu. Bấm 'Tạo đề' để AI soạn câu hỏi.")
    return RedirectResponse("/gv", status_code=303)


def _clean_title(raw: str) -> str:
    """Tiêu đề do giáo viên gõ: bỏ khoảng trắng thừa, giới hạn độ dài; rỗng nghĩa là dùng tên tự sinh."""
    return " ".join(str(raw).split())[:MAX_TITLE_LEN]


def _clamp_n(raw: str) -> int:
    try:
        return max(MIN_QUESTIONS, min(MAX_QUESTIONS, int(raw)))
    except ValueError:
        return DEFAULT_QUESTIONS


@router.post("/tao-de/tai-lieu/{material_id}")
async def create_from_material(
    request: Request, material_id: int, n: str = Form(str(DEFAULT_QUESTIONS)), title: str = Form("")
):
    if not _is_teacher(request):
        return _deny(request)
    material = materials.get_material(material_id)
    if material is None:
        return _back(request, "Không tìm thấy tài liệu")
    try:
        attachment = materials.load_attachment(material)
        quiz, source = await run_in_threadpool(
            generate_quiz, attachment, material["grade"], _clamp_n(n), material["title"], f"lop{material['grade']}"
        )
    except (AIError, materials.MaterialError) as exc:
        log.warning("Tạo đề lỗi: %s", exc)
        return _back(request, f"AI chưa tạo được đề: {exc}. Thử lại sau ít phút.")
    quiz["title"] = _clean_title(title) or quiz["title"]
    quiz_id = quizzes.create_quiz(material_id, material["grade"], quiz, source)
    return RedirectResponse(f"/gv/de/{quiz_id}", status_code=303)


@router.post("/tao-de/sgk")
async def create_from_textbook(
    request: Request,
    grade: str = Form(""),
    lesson_ids: list[str] = Form([]),
    semester: str = Form(""),
    n: str = Form(str(DEFAULT_QUESTIONS)),
    title: str = Form(""),
):
    if not _is_teacher(request):
        return _deny(request)
    sem = int(semester) if semester in ("1", "2") else None
    lessons = library.semester_lessons(grade, sem) if sem else library.find_lessons(grade, lesson_ids)
    if grade not in GRADES or not lessons:
        return _back(request, "Hãy chọn ít nhất một bài học hoặc một học kỳ")
    auto_title = library.lessons_title(lessons, grade, sem)
    try:
        attachment = library.lessons_attachment(grade, lessons)
        quiz, source = await run_in_threadpool(
            generate_quiz, attachment, grade, _clamp_n(n), auto_title, lessons[0]["id"]
        )
    except (AIError, ValueError) as exc:
        log.warning("Tạo đề SGK lỗi: %s", exc)
        return _back(request, f"AI chưa tạo được đề: {exc}")
    if source == "ai":
        quiz["title"] = auto_title
    quiz["title"] = _clean_title(title) or quiz["title"]
    quiz_id = quizzes.create_quiz(None, grade, quiz, source)
    return RedirectResponse(f"/gv/de/{quiz_id}", status_code=303)


@router.post("/de/{quiz_id}/tieu-de")
def rename_quiz(request: Request, quiz_id: int, title: str = Form("")):
    """Giáo viên đặt lại tên đề, ví dụ 'Ôn tập giữa kỳ I lớp 4.2'."""
    if not _is_teacher(request):
        return _deny(request)
    if quizzes.get_quiz(quiz_id) is None:
        return _back(request, "Không tìm thấy đề")
    cleaned = _clean_title(title)
    if not cleaned:
        return _back(request, "Tên đề không được để trống", f"/gv/de/{quiz_id}")
    quizzes.set_title(quiz_id, cleaned)
    set_flash(request, "Đã đổi tên đề")
    return RedirectResponse(f"/gv/de/{quiz_id}", status_code=303)


@router.get("/de/{quiz_id}")
def quiz_detail(request: Request, quiz_id: int):
    if not _is_teacher(request):
        return _deny(request)
    quiz = quizzes.get_quiz(quiz_id)
    if quiz is None:
        return _back(request, "Không tìm thấy đề")
    return render(request, "gv_quiz.html", quiz=quiz, report=attempts.quiz_report(quiz_id))


def _keep_answer_by_content(q: dict[str, Any], options: list[str], typed: str) -> str:
    """Đáp án đi theo NỘI DUNG lựa chọn: xóa hoặc thêm lựa chọn thì chữ cái tự cập nhật.
    Nếu giáo viên gõ chữ cái khác với trước, ưu tiên chữ cái mới (phải có trong danh sách)."""
    letters = [o[0] for o in options]
    typed = typed[:1].upper()
    if typed and typed != q["answer"] and typed in letters:
        return typed
    old = next((o for o in q["options"] if o[:1].upper() == q["answer"][:1].upper()), "")
    old_body = old[3:].strip().lower() if old[1:3] == ". " else old.strip().lower()
    for o in options:
        if o[3:].strip().lower() == old_body:
            return o[0]
    return typed if typed in letters else letters[0]


def _edit_for_question(form: Any, q: dict[str, Any]) -> dict[str, Any]:
    """Ghép bản sửa của một câu; dữ liệu thiếu hoặc không hợp lệ thì giữ giá trị cũ."""
    qid = q["id"]
    answer = str(form.get(f"answer_{qid}", q["answer"])).strip() or q["answer"]
    options = q["options"]
    if q["qtype"] == "mcq":
        sent = [str(form.get(f"opt_{qid}_{i}", "")).strip()[:MAX_OPTION_LEN] for i in range(MAX_OPTIONS)]
        cleaned = [o for o in sent if o]
        if len(cleaned) >= 2:
            options = _relabel_options(cleaned)
        answer = _keep_answer_by_content(q, options, answer)
    elif q["qtype"] == "match":
        lines = str(form.get(f"pairs_{qid}", "")).splitlines()
        pairs = clean_pairs([line.split("=", 1) for line in lines if "=" in line])
        options = pairs if len(pairs) >= 2 else q["options"]
        answer = ""
    else:
        bank = [w.strip() for w in str(form.get(f"bank_{qid}", "")).split(",") if w.strip()]
        options = sorted(dict.fromkeys(bank[:5]), key=str.lower)
        if options and answer.lower() not in [w.lower() for w in options]:
            options = sorted(list(dict.fromkeys([answer] + options))[:5], key=str.lower)
    return {
        "id": qid,
        "prompt": str(form.get(f"prompt_{qid}", q["prompt"])).strip() or q["prompt"],
        "answer": answer,
        "explanation": str(form.get(f"explanation_{qid}", q["explanation"])).strip(),
        "options": options,
        "image_path": _image_for_question(form, q),
    }


def _image_for_question(form: Any, q: dict[str, Any]) -> str:
    """Giữ ảnh cũ, thay bằng ảnh mới tải lên, hoặc xóa nếu giáo viên tick 'Xóa ảnh'."""
    current = q.get("image_path", "") or ""
    upload = form.get(f"img_{q['id']}")
    data = getattr(upload, "file", None)
    raw = data.read(images.MAX_IMAGE_BYTES + 1) if data is not None else b""
    if not raw:
        if form.get(f"xoa_anh_{q['id']}"):
            images.delete_image(current)
            return ""
        return current
    try:
        name = images.save_image(raw)
    except images.ImageError as exc:
        raise ValueError(f"Câu {q['position']}: {exc}") from exc
    return name


def _parse_edits(form: Any, quiz: dict[str, Any]) -> list[dict[str, Any]]:
    return [_edit_for_question(form, q) for q in quiz["questions"]]


@router.post("/de/{quiz_id}/luu")
async def quiz_save(request: Request, quiz_id: int):
    if not _is_teacher(request):
        return _deny(request)
    quiz = quizzes.get_quiz(quiz_id)
    if quiz is None:
        return _back(request, "Không tìm thấy đề")
    form = await request.form()
    try:
        edits = _parse_edits(form, quiz)
    except ValueError as exc:
        return _back(request, str(exc), f"/gv/de/{quiz_id}")
    quizzes.update_questions(quiz_id, edits)
    old_images = {q["id"]: q.get("image_path", "") for q in quiz["questions"]}
    for e in edits:  # ảnh cũ chỉ xóa sau khi DB đã trỏ sang ảnh mới
        if old_images.get(e["id"]) and old_images[e["id"]] != e.get("image_path", ""):
            images.delete_image(old_images[e["id"]])
    set_flash(request, "Đã lưu chỉnh sửa")
    return RedirectResponse(f"/gv/de/{quiz_id}", status_code=303)


@router.post("/de/{quiz_id}/cau/{question_id}/xoa")
def question_delete(request: Request, quiz_id: int, question_id: int):
    if not _is_teacher(request):
        return _deny(request)
    quiz = quizzes.get_quiz(quiz_id)
    if quiz is None:
        return _back(request, "Không tìm thấy đề")
    if len(quiz["questions"]) <= 1:
        return _back(request, "Đề phải còn ít nhất 1 câu", f"/gv/de/{quiz_id}")
    gone = next((q for q in quiz["questions"] if q["id"] == question_id), None)
    if gone and gone.get("image_path"):
        images.delete_image(gone["image_path"])
    remaining = quizzes.delete_question(quiz_id, question_id)
    set_flash(request, f"Đã xóa câu, còn {remaining} câu")
    return RedirectResponse(f"/gv/de/{quiz_id}", status_code=303)


@router.post("/de/{quiz_id}/trang-thai")
def quiz_status(request: Request, quiz_id: int, status: str = Form("")):
    if not _is_teacher(request):
        return _deny(request)
    if status not in STATUS_LABEL:
        return _back(request, "Trạng thái không hợp lệ", f"/gv/de/{quiz_id}")
    quizzes.set_status(quiz_id, status)
    set_flash(request, STATUS_LABEL[status])
    return RedirectResponse(f"/gv/de/{quiz_id}", status_code=303)


@router.post("/de/{quiz_id}/xoa")
def quiz_delete(request: Request, quiz_id: int):
    if not _is_teacher(request):
        return _deny(request)
    quiz = quizzes.get_quiz(quiz_id)
    for q in (quiz or {}).get("questions", []):
        if q.get("image_path"):
            images.delete_image(q["image_path"])
    quizzes.delete_quiz(quiz_id)
    set_flash(request, "Đã xóa đề")
    return RedirectResponse("/gv", status_code=303)


@router.post("/de/{quiz_id}/luot-trung")
def dedupe(request: Request, quiz_id: int):
    if not _is_teacher(request):
        return _deny(request)
    n = attempts.dedupe_quiz(quiz_id)
    set_flash(request, f"Đã xóa {n} lượt trùng" if n else "Không có lượt trùng")
    return RedirectResponse(f"/gv/de/{quiz_id}", status_code=303)


@router.post("/luot/{attempt_id}/xoa")
def attempt_delete(request: Request, attempt_id: int):
    if not _is_teacher(request):
        return _deny(request)
    attempt = attempts.get_attempt(attempt_id)
    if attempt is None:
        return _back(request, "Không tìm thấy lượt làm")
    attempts.delete_attempt(attempt_id)
    set_flash(request, f"Đã xóa lượt làm của {attempt['student_name']}")
    return RedirectResponse(f"/gv/de/{attempt['quiz_id']}", status_code=303)


def _csv_safe(text: str) -> str:
    """Chặn công thức Excel chạy từ ô dữ liệu người dùng nhập (=, +, -, @)."""
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.get("/de/{quiz_id}/word")
def quiz_word(request: Request, quiz_id: int, dap_an: str = ""):
    """Tải đề ra Word để in; thêm ?dap_an=1 để kèm trang đáp án cho giáo viên."""
    if not _is_teacher(request):
        return _deny(request)
    quiz = quizzes.get_quiz(quiz_id)
    if quiz is None:
        return _back(request, "Không tìm thấy đề")
    with_answers = dap_an == "1"
    data = export_docx.build_quiz_docx(quiz, with_answers)
    name = f"de-{quiz['code']}{'-dap-an' if with_answers else ''}.docx"
    headers = {"Content-Disposition": f"attachment; filename={name}"}
    return StreamingResponse(io.BytesIO(data), media_type=DOCX_MIME, headers=headers)


@router.get("/de/{quiz_id}/csv")
def quiz_csv(request: Request, quiz_id: int):
    if not _is_teacher(request):
        return _deny(request)
    if quizzes.get_quiz(quiz_id) is None:
        return _back(request, "Không tìm thấy đề")
    report = attempts.quiz_report(quiz_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    fb = {f["attempt_id"]: f for f in report["feedback"]}
    writer.writerow(["Học sinh", "Điểm", "Tổng", "Thời gian", "Cảm nhận", "Nhận xét"])
    for a in report["attempts"]:
        f = fb.get(a["id"], {})
        writer.writerow([_csv_safe(a["student_name"]), a["score"], a["total"], a["created_at"], f.get("label", ""), _csv_safe(f.get("comment", ""))])
    headers = {"Content-Disposition": f"attachment; filename=ket-qua-de-{quiz_id}.csv"}
    return StreamingResponse(iter(["﻿" + buf.getvalue()]), media_type="text/csv", headers=headers)


@router.get("/bxh/{quiz_id}")
def teacher_leaderboard(request: Request, quiz_id: int):
    if not _is_teacher(request):
        return _deny(request)
    quiz = quizzes.get_quiz(quiz_id)
    if quiz is None:
        return _back(request, "Không tìm thấy đề")
    return render(request, "hs_bxh.html", quiz=quiz, rows=attempts.leaderboard(quiz_id), teacher_view=True)


@router.get("/luot/{attempt_id}")
def attempt_detail(request: Request, attempt_id: int):
    if not _is_teacher(request):
        return _deny(request)
    attempt = attempts.get_attempt(attempt_id)
    if attempt is None:
        return _back(request, "Không tìm thấy lượt làm")
    return render(request, "hs_ket_qua.html", attempt=attempt, teacher_view=True, feedback=attempts.get_feedback(attempt_id))
