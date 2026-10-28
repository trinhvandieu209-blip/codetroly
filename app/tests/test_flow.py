"""Kiểm thử luồng end-to-end ở chế độ không AI."""
import re


def _create_seed_quiz(teacher):
    r = teacher.post("/gv/tao-de/sgk", data={"grade": "3", "lesson_ids": ["b1"], "n": "10"}, follow_redirects=False)
    assert r.status_code == 303
    quiz_id = int(r.headers["location"].rsplit("/", 1)[1])
    page = teacher.get(f"/gv/de/{quiz_id}").text
    code = re.search(r'class="code">([A-Z0-9]{6})<', page).group(1)
    return quiz_id, code


def test_khu_vuc_giao_vien_can_pin(app_client):
    r = app_client.get("/gv", follow_redirects=False)
    assert r.status_code == 303 and "/gv/dang-nhap" in r.headers["location"]


def test_pin_sai_bi_tu_choi(app_client):
    r = app_client.post("/gv/dang-nhap", data={"pin": "0000"}, follow_redirects=False)
    assert r.headers["location"] == "/gv/dang-nhap"


def test_tao_de_tu_sgk_che_do_mau(teacher):
    quiz_id, code = _create_seed_quiz(teacher)
    page = teacher.get(f"/gv/de/{quiz_id}").text
    assert "Thông tin và quyết định" in page and "Nháp" in page


def test_hoc_sinh_khong_vao_duoc_de_nhap(teacher):
    _, code = _create_seed_quiz(teacher)
    r = teacher.post("/vao-bai", data={"code": code, "name": "Minh"}, follow_redirects=False)
    assert r.headers["location"] == "/"


def test_luong_hoc_sinh_lam_bai_goi_y_ke_hoach(teacher):
    quiz_id, code = _create_seed_quiz(teacher)
    teacher.post(f"/gv/de/{quiz_id}/trang-thai", data={"status": "published"})
    teacher.get("/gv/dang-xuat")
    hs = teacher
    r = hs.post("/vao-bai", data={"code": code.lower(), "name": "Minh 3A1"}, follow_redirects=False)
    assert r.headers["location"] == f"/lam-bai/{code}"
    page = hs.get(f"/lam-bai/{code}")
    assert page.status_code == 200 and "Minh 3A1" in page.text
    ids = [int(x) for x in re.findall(r'name="q_(\d+)"', page.text)]
    ids = list(dict.fromkeys(ids))
    answers = {f"q_{ids[0]}": "A", f"q_{ids[1]}": "A"}  # câu 2 đáp án đúng là B -> sai
    for qid in ids[2:]:
        answers[f"q_{qid}"] = "thông tin"
    r = hs.post(f"/lam-bai/{code}", data=answers, follow_redirects=False)
    attempt_id = int(r.headers["location"].rsplit("/", 1)[1])
    result = hs.get(f"/ket-qua/{attempt_id}").text
    assert "Kế hoạch ôn tập" in result and "❌" in result and "✅" in result
    hint = hs.post(f"/goi-y/{attempt_id}/{ids[1]}").json()
    assert "hint" in hint and "answer" not in hint
    hs.post(f"/goi-y/{attempt_id}/{ids[1]}")
    third = hs.post(f"/goi-y/{attempt_id}/{ids[1]}").json()
    assert third["answer"] == "B" and third["explanation"]
    hs.post(f"/goi-y/{attempt_id}/{ids[1]}")
    assert hs.get(f"/ket-qua/{attempt_id}").text.count('class="goiy"') == 3
    dung = hs.post(f"/goi-y/{attempt_id}/{ids[0]}").json()
    assert "đã làm đúng" in dung["hint"]


def test_hoc_sinh_khac_khong_xem_duoc_ket_qua_nguoi_khac(teacher):
    quiz_id, code = _create_seed_quiz(teacher)
    teacher.post(f"/gv/de/{quiz_id}/trang-thai", data={"status": "published"})
    teacher.get("/gv/dang-xuat")
    teacher.post("/vao-bai", data={"code": code, "name": "An"})
    page = teacher.get(f"/lam-bai/{code}").text
    ids = list(dict.fromkeys(re.findall(r'name="q_(\d+)"', page)))
    r = teacher.post(f"/lam-bai/{code}", data={f"q_{i}": "A" for i in ids}, follow_redirects=False)
    attempt_id = int(r.headers["location"].rsplit("/", 1)[1])
    teacher.cookies.clear()
    r = teacher.get(f"/ket-qua/{attempt_id}", follow_redirects=False)
    assert r.status_code == 303


def test_bao_cao_va_csv(teacher):
    quiz_id, code = _create_seed_quiz(teacher)
    teacher.post(f"/gv/de/{quiz_id}/trang-thai", data={"status": "published"})
    teacher.post("/vao-bai", data={"code": code, "name": "Khoa"})
    page = teacher.get(f"/lam-bai/{code}").text
    ids = list(dict.fromkeys(re.findall(r'name="q_(\d+)"', page)))
    teacher.post(f"/lam-bai/{code}", data={f"q_{i}": "A" for i in ids})
    report = teacher.get(f"/gv/de/{quiz_id}").text
    assert "Khoa" in report and "lượt làm" in report
    csv = teacher.get(f"/gv/de/{quiz_id}/csv")
    assert csv.status_code == 200 and "Khoa" in csv.text


def test_tai_lieu_tu_choi_dinh_dang_la(teacher):
    r = teacher.post("/gv/tai-lieu", data={"title": "x", "grade": "3"}, files={"file": ("a.exe", b"abc", "application/octet-stream")})
    assert "Chỉ nhận PDF" in r.text


def test_tai_lieu_txt_va_tao_de_mau(teacher):
    r = teacher.post("/gv/tai-lieu", data={"title": "Ôn tập", "grade": "4"}, files={"file": ("on.txt", "Phần cứng và phần mềm".encode(), "text/plain")})
    assert "Đã lưu tài liệu" in r.text
    r = teacher.post("/gv/tao-de/tai-lieu/1", data={"n": "5"}, follow_redirects=False)
    assert r.status_code == 303 and "/gv/de/" in r.headers["location"]


def test_sua_cau_hoi_va_xoa_de(teacher):
    quiz_id, _ = _create_seed_quiz(teacher)
    page = teacher.get(f"/gv/de/{quiz_id}").text
    qid = re.search(r'name="prompt_(\d+)"', page).group(1)
    r = teacher.post(f"/gv/de/{quiz_id}/luu", data={f"prompt_{qid}": "Câu hỏi đã sửa", f"answer_{qid}": "A"})
    assert "Câu hỏi đã sửa" in r.text
    r = teacher.post(f"/gv/de/{quiz_id}/xoa")
    assert "Đã xóa đề" in r.text


def test_health(app_client):
    assert app_client.get("/health").json() == {"status": "ok"}


def test_khoa_pin_sau_5_lan_sai(app_client):
    for _ in range(5):
        app_client.post("/gv/dang-nhap", data={"pin": "0000"})
    r = app_client.post("/gv/dang-nhap", data={"pin": "9999"}, follow_redirects=False)
    assert r.headers["location"] == "/gv/dang-nhap"


def test_upload_khong_dang_nhap_bi_chan_truoc_khi_doc(app_client):
    r = app_client.post("/gv/tai-lieu", data={"title": "x", "grade": "3"}, files={"file": ("a.txt", b"abc", "text/plain")}, follow_redirects=False)
    assert r.status_code == 303 and "/gv/dang-nhap" in r.headers["location"]


def test_lua_chon_chua_html_duoc_escape(teacher):
    quiz_id, code = _create_seed_quiz(teacher)
    page = teacher.get(f"/gv/de/{quiz_id}").text
    qid = re.search(r'name="prompt_(\d+)"', page).group(1)
    teacher.post(f"/gv/de/{quiz_id}/luu", data={f"prompt_{qid}": "q", f"answer_{qid}": "A", f"opt_{qid}_0": "A. <img src=x onerror=alert(1)>", f"opt_{qid}_1": "B. y", f"opt_{qid}_2": "C. z"})
    teacher.post(f"/gv/de/{quiz_id}/trang-thai", data={"status": "published"})
    teacher.post("/vao-bai", data={"code": code, "name": "Bo"})
    page = teacher.get(f"/lam-bai/{code}").text
    ids = list(dict.fromkeys(re.findall(r'name="q_(\d+)"', page)))
    r = teacher.post(f"/lam-bai/{code}", data={f"q_{i}": "A" for i in ids})
    assert "<img src=x" not in r.text and "&lt;img" in r.text


def test_hoc_sinh_lam_hai_bai_van_xem_duoc_ket_qua_bai_dau(teacher):
    q1, c1 = _create_seed_quiz(teacher)
    q2, c2 = _create_seed_quiz(teacher)
    for q in (q1, q2):
        teacher.post(f"/gv/de/{q}/trang-thai", data={"status": "published"})
    teacher.get("/gv/dang-xuat")
    teacher.post("/vao-bai", data={"code": c1, "name": "Na"})
    ids = list(dict.fromkeys(re.findall(r'name="q_(\d+)"', teacher.get(f"/lam-bai/{c1}").text)))
    r1 = teacher.post(f"/lam-bai/{c1}", data={f"q_{i}": "A" for i in ids}, follow_redirects=False)
    a1 = r1.headers["location"]
    teacher.post("/vao-bai", data={"code": c2, "name": "Na"})
    assert teacher.get(f"/lam-bai/{c2}").status_code == 200
    assert teacher.get(a1, follow_redirects=False).status_code == 200


def test_de_mau_dung_khoi_lop(teacher):
    r = teacher.post("/gv/tao-de/sgk", data={"grade": "5", "lesson_ids": ["b1"], "n": "5"}, follow_redirects=False)
    page = teacher.get(r.headers["location"]).text
    assert "Tin học 5" in page


def test_header_x_forwarded_for_khong_qua_mat_khoa_pin(app_client):
    for i in range(5):
        app_client.post("/gv/dang-nhap", data={"pin": "0000"}, headers={"X-Forwarded-For": f"10.0.0.{i}"})
    r = app_client.post("/gv/dang-nhap", data={"pin": "9999"}, headers={"X-Forwarded-For": "10.0.0.99"}, follow_redirects=False)
    assert r.headers["location"] == "/gv/dang-nhap"


def test_sua_de_thieu_lua_chon_thi_giu_nguyen(teacher):
    quiz_id, _ = _create_seed_quiz(teacher)
    page = teacher.get(f"/gv/de/{quiz_id}").text
    qid = re.search(r'name="prompt_(\d+)"', page).group(1)
    r = teacher.post(f"/gv/de/{quiz_id}/luu", data={f"prompt_{qid}": "q", f"answer_{qid}": "Z"})
    assert r.text.count(f'name="opt_{qid}_') == 5 and f'name="answer_{qid}" value="A"' in r.text and 'value="C. ' in r.text


def _publish_and_enter(teacher, name="Na"):
    quiz_id, code = _create_seed_quiz(teacher)
    teacher.post(f"/gv/de/{quiz_id}/trang-thai", data={"status": "published"})
    teacher.get("/gv/dang-xuat")
    teacher.post("/vao-bai", data={"code": code, "name": name})
    page = teacher.get(f"/lam-bai/{code}").text
    ids = list(dict.fromkeys(re.findall(r'name="q_(\d+)"', page)))
    r = teacher.post(f"/lam-bai/{code}", data={f"q_{i}": "A" for i in ids}, follow_redirects=False)
    return quiz_id, code, int(r.headers["location"].rsplit("/", 1)[1])


def test_hoc_sinh_gui_nhan_xet_va_giao_vien_thay(teacher):
    quiz_id, code, aid = _publish_and_enter(teacher, "Bi")
    r = teacher.post(f"/phan-hoi/{aid}", data={"rating": "3", "comment": "Em thích gợi ý"})
    assert "Cảm ơn em" in r.text and "Em thích gợi ý" in r.text
    r = teacher.post(f"/phan-hoi/{aid}", data={"rating": "9"}, follow_redirects=False)
    assert r.status_code == 303
    teacher.post("/gv/dang-nhap", data={"pin": "9999"})
    page = teacher.get(f"/gv/de/{quiz_id}").text
    assert "Em thích gợi ý" in page and "100% thích" in page
    assert "Thích,Em thích gợi ý" in teacher.get(f"/gv/de/{quiz_id}/csv").text


def test_xoa_cau_va_them_lua_chon(teacher):
    quiz_id, _ = _create_seed_quiz(teacher)
    page = teacher.get(f"/gv/de/{quiz_id}").text
    qids = re.findall(r'name="prompt_(\d+)"', page)
    n0 = len(qids)
    r = teacher.post(f"/gv/de/{quiz_id}/cau/{qids[0]}/xoa")
    assert f"còn {n0 - 1} câu" in r.text
    qid = qids[1]
    r = teacher.post(f"/gv/de/{quiz_id}/luu", data={f"prompt_{qid}": "q", f"answer_{qid}": "D", f"opt_{qid}_0": "x", f"opt_{qid}_1": "y", f"opt_{qid}_2": "z", f"opt_{qid}_3": "t"})
    assert 'value="D. t"' in r.text and f'name="answer_{qid}" value="D"' in r.text


def test_cau_ngan_co_tu_goi_y(teacher):
    quiz_id, code = _create_seed_quiz(teacher)
    page = teacher.get(f"/gv/de/{quiz_id}").text
    qid = re.search(r'name="bank_(\d+)"', page).group(1)
    teacher.post(f"/gv/de/{quiz_id}/luu", data={f"prompt_{qid}": "Con người cần gì để ra quyết định?", f"answer_{qid}": "thông tin", f"bank_{qid}": "quyết định, hình ảnh, âm thanh"})
    teacher.post(f"/gv/de/{quiz_id}/trang-thai", data={"status": "published"})
    teacher.post("/vao-bai", data={"code": code, "name": "Tí"})
    page = teacher.get(f"/lam-bai/{code}").text
    assert page.count('class="chip"') == 4 and ">thông tin<" in page


def test_nop_bai_hai_lan_chi_tao_mot_luot(teacher, monkeypatch):
    from services import attempts as svc

    monkeypatch.setattr(svc, "_recent_attempt", lambda quiz_id, name: None)
    quiz_id, code = _create_seed_quiz(teacher)
    teacher.post(f"/gv/de/{quiz_id}/trang-thai", data={"status": "published"})
    teacher.get("/gv/dang-xuat")
    teacher.post("/vao-bai", data={"code": code, "name": "Trang"})
    page = teacher.get(f"/lam-bai/{code}").text
    ids = list(dict.fromkeys(re.findall(r'name="q_(\d+)"', page)))
    r1 = teacher.post(f"/lam-bai/{code}", data={f"q_{i}": "A" for i in ids}, follow_redirects=False)
    r2 = teacher.post(f"/lam-bai/{code}", data={f"q_{i}": "A" for i in ids}, follow_redirects=False)
    assert r1.headers["location"] == r2.headers["location"]
    teacher.post("/vao-bai", data={"code": code, "name": "Trang"})
    r3 = teacher.post(f"/lam-bai/{code}", data={f"q_{i}": "A" for i in ids}, follow_redirects=False)
    assert r3.headers["location"] != r1.headers["location"]


def test_xoa_luot_trung_giu_luot_co_nhan_xet(teacher):
    from services import attempts as svc, quizzes as qz

    quiz_id, code = _create_seed_quiz(teacher)
    quiz = qz.get_quiz(quiz_id)
    given = {q["id"]: "A" for q in quiz["questions"]}
    a1 = svc._create_attempt(quiz, "Long", given)
    a2 = svc._create_attempt(quiz, "Long", given)
    a3 = svc._create_attempt(quiz, "Long", given)
    svc._create_attempt(quiz, "Long", {q["id"]: "B" for q in quiz["questions"]})  # điểm khác, giữ
    svc.save_feedback(a2, 3, "hay")
    r = teacher.post(f"/gv/de/{quiz_id}/luot-trung")
    assert "Đã xóa 2 lượt trùng" in r.text
    left = [a["id"] for a in svc.quiz_report(quiz_id)["attempts"]]
    assert a2 in left and a1 not in left and a3 not in left and len(left) == 2
    r = teacher.post(f"/gv/luot/{a2}/xoa")
    assert "Đã xóa lượt làm của Long" in r.text


def test_ten_go_bua_bi_tu_choi(teacher):
    quiz_id, code = _create_seed_quiz(teacher)
    teacher.post(f"/gv/de/{quiz_id}/trang-thai", data={"status": "published"})
    teacher.get("/gv/dang-xuat")
    for bad in ("dfs", "x", "123", "..."):
        r = teacher.post("/vao-bai", data={"code": code, "name": bad}, follow_redirects=False)
        assert r.headers["location"] == "/", bad
    for ok in ("Minh 4.3", "Tí", "nguyễn ngọc phương trang lớp 4.3"):
        r = teacher.post("/vao-bai", data={"code": code, "name": ok}, follow_redirects=False)
        assert "/lam-bai/" in r.headers["location"], ok


def test_nop_song_song_chi_tao_mot_luot(teacher):
    import concurrent.futures as cf
    from services import attempts as svc, quizzes as qz

    quiz_id, _ = _create_seed_quiz(teacher)
    quiz = qz.get_quiz(quiz_id)
    given = {q["id"]: "A" for q in quiz["questions"]}
    with cf.ThreadPoolExecutor(6) as ex:
        ids = list(ex.map(lambda _: svc.submit_attempt(quiz, "Bông 4.3", given), range(6)))
    assert len(set(ids)) == 1


def test_xoa_cau_tinh_lai_diem_luot_da_lam(teacher):
    from services import attempts as svc, quizzes as qz

    quiz_id, _ = _create_seed_quiz(teacher)
    quiz = qz.get_quiz(quiz_id)
    q0 = quiz["questions"][0]
    aid = svc.submit_attempt(quiz, "Mai", {q0["id"]: q0["answer"]})
    before = svc.get_attempt(aid)
    assert before["score"] == 1 and before["total"] == len(quiz["questions"])
    teacher.post(f"/gv/de/{quiz_id}/cau/{q0['id']}/xoa")
    after = svc.get_attempt(aid)
    assert after["score"] == 0 and after["total"] == len(quiz["questions"]) - 1


def test_xoa_luot_trung_khong_gop_hai_em_cung_ten_khac_bai(teacher):
    from services import attempts as svc, quizzes as qz

    quiz_id, _ = _create_seed_quiz(teacher)
    quiz = qz.get_quiz(quiz_id)
    qs = quiz["questions"]
    a = svc._create_attempt(quiz, "Lan 4.3", {qs[0]["id"]: "A"})
    b = svc._create_attempt(quiz, "Lan 4.3", {qs[1]["id"]: "A"})
    teacher.post(f"/gv/de/{quiz_id}/luot-trung")
    left = {x["id"] for x in svc.quiz_report(quiz_id)["attempts"]}
    assert {a, b} <= left


def test_id_khong_phai_so_va_csv_de_khong_ton_tai(teacher):
    assert teacher.get("/gv/de/abc", follow_redirects=False).headers["location"] == "/gv"
    assert teacher.post("/phan-hoi/abc", data={"rating": "3"}, follow_redirects=False).headers["location"] == "/"
    assert teacher.get("/gv/de/99999/csv", follow_redirects=False).status_code == 303


def test_csv_chan_cong_thuc_excel(teacher):
    from routes.teacher import _csv_safe

    quiz_id, code, aid = _publish_and_enter(teacher, "Lan 4.3")
    teacher.post(f"/phan-hoi/{aid}", data={"rating": "3", "comment": "=cmd(1)"})
    teacher.post("/gv/dang-nhap", data={"pin": "9999"})
    csv = teacher.get(f"/gv/de/{quiz_id}/csv").text
    assert "'=cmd(1)" in csv and _csv_safe("=SUM(1)") == "'=SUM(1)" and _csv_safe("Lan") == "Lan"


def test_xoa_lua_chon_khong_lech_dap_an(teacher):
    quiz_id, _ = _create_seed_quiz(teacher)
    page = teacher.get(f"/gv/de/{quiz_id}").text
    qid = re.search(r'name="prompt_(\d+)"', page).group(1)
    # câu 1 seed: đáp án A "Đã đến giờ đi học"; đổi thành B rồi xóa A -> đáp án phải thành A (nội dung cũ của B)
    teacher.post(f"/gv/de/{quiz_id}/luu", data={f"prompt_{qid}": "q", f"answer_{qid}": "B", f"opt_{qid}_0": "A. x", f"opt_{qid}_1": "B. Trời sắp mưa", f"opt_{qid}_2": "C. z"})
    r = teacher.post(f"/gv/de/{quiz_id}/luu", data={f"prompt_{qid}": "q", f"answer_{qid}": "B", f"opt_{qid}_0": "", f"opt_{qid}_1": "B. Trời sắp mưa", f"opt_{qid}_2": "C. z"})
    assert f'name="answer_{qid}" value="A"' in r.text and 'value="A. Trời sắp mưa"' in r.text


def test_body_qua_lon_va_origin_la_bi_chan(app_client):
    r = app_client.post("/vao-bai", data={"code": "x", "name": "y"}, headers={"content-length": str(10 * 1024 * 1024)}, follow_redirects=False)
    assert r.status_code == 303
    r = app_client.post("/vao-bai", data={"code": "x", "name": "y"}, headers={"origin": "https://ke-xau.vn"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_hoc_sinh_thoat_xoa_phien(teacher):
    quiz_id, code, aid = _publish_and_enter(teacher, "Na 4.3")
    assert teacher.get(f"/ket-qua/{aid}").status_code == 200
    teacher.get("/thoat")
    assert teacher.get(f"/ket-qua/{aid}", follow_redirects=False).status_code == 303


def test_bao_cao_hien_lan_lam_lai(teacher):
    from services import attempts as svc, quizzes as qz

    quiz_id, _ = _create_seed_quiz(teacher)
    quiz = qz.get_quiz(quiz_id)
    svc._create_attempt(quiz, "Tí 4.3", {})
    svc._create_attempt(quiz, "Tí 4.3", {})
    assert "(lần 2)" in teacher.get(f"/gv/de/{quiz_id}").text


def _quiz_with_match(teacher):
    """Tạo đề mẫu rồi thêm một câu nối ghép bằng service, trả về (quiz_id, code)."""
    from services import quizzes as qz

    quiz_id, code = _create_seed_quiz(teacher)
    quiz = qz.get_quiz(quiz_id)
    q = quiz["questions"][0]
    qz.update_questions(quiz_id, [{"id": q["id"], "prompt": "Nối", "answer": "", "explanation": "", "options": [["Chuột", "Thiết bị vào"], ["Màn hình", "Thiết bị ra"]]}])
    with __import__("db").connect() as conn:
        conn.execute("UPDATE questions SET qtype='match' WHERE id=?", (q["id"],))
    return quiz_id, code, q["id"]


def test_lam_bai_co_cau_noi_ghep_va_cham(teacher):
    quiz_id, code, mid = _quiz_with_match(teacher)
    teacher.post(f"/gv/de/{quiz_id}/trang-thai", data={"status": "published"})
    teacher.get("/gv/dang-xuat")
    teacher.post("/vao-bai", data={"code": code, "name": "Bi 4.3"})
    page = teacher.get(f"/lam-bai/{code}").text
    assert 'class="o trai"' in page and "Hoặc ôn tập qua game" in page
    ids = list(dict.fromkeys(re.findall(r'name="q_(\d+)"', page)))
    tok = {text: t for t, text in re.findall(r'class="o phai" data-j="([a-f0-9]+)"[^>]*>([^<]+)<', page)}
    assert "0:0" not in page and len(tok) == 2  # vế phải chỉ có token ngẫu nhiên, không lộ thứ tự gốc
    data = {f"q_{i}": "A" for i in ids}
    data[f"q_{mid}"] = f"0:{tok['Thiết bị vào']},1:{tok['Thiết bị ra']}"
    r = teacher.post(f"/lam-bai/{code}", data=data)
    assert "Nối đúng hết" in r.text and "Nối đúng tất cả" in r.text
    # gửi chỉ số gốc thay vì token thì không được tính
    teacher.post("/vao-bai", data={"code": code, "name": "Bo 4.3"})
    data[f"q_{mid}"] = "0:0,1:1"
    r = teacher.post(f"/lam-bai/{code}", data=data)
    assert "Nối đúng hết" not in r.text


def test_giao_vien_sua_cap_noi_va_anh(teacher):
    quiz_id, code, mid = _quiz_with_match(teacher)
    png = b"\x89PNG\r\n" + b"0" * 20
    r = teacher.post(f"/gv/de/{quiz_id}/luu", data={f"pairs_{mid}": "Bàn phím = Gõ chữ\nLoa = Phát âm thanh\nMàn hình = Hiển thị"}, files={f"img_{mid}": ("a.png", png, "image/png")})
    assert "Bàn phím = Gõ chữ" in r.text and "đang có ảnh" in r.text
    name = re.search(r'/anh/([a-f0-9]+\.png)', r.text).group(1)
    assert teacher.get(f"/anh/{name}").status_code == 200
    assert teacher.get("/anh/../x.png", follow_redirects=False).status_code in (303, 404)
    r = teacher.post(f"/gv/de/{quiz_id}/luu", data={f"xoa_anh_{mid}": "1"})
    assert "đang có ảnh" not in r.text


def test_choi_game_tao_luot_va_bang_xep_hang(teacher):
    quiz_id, code, mid = _quiz_with_match(teacher)
    teacher.post(f"/gv/de/{quiz_id}/trang-thai", data={"status": "published"})
    teacher.get("/gv/dang-xuat")
    teacher.post("/vao-bai", data={"code": code, "name": "Tèo 4.3"})
    page = teacher.get(f"/game/{code}").text
    assert "questions_json" not in page and '"answer"' not in page and "điểm" in page
    from services import quizzes as qz
    quiz = qz.get_quiz(quiz_id)
    total = 0
    for q in quiz["questions"]:
        given = "0:0,1:1" if q["qtype"] == "match" else (q["answer"] if q["qtype"] == "mcq" else "thông tin")
        j = teacher.post(f"/game/{code}/tra-loi", json={"question_id": q["id"], "given": given, "elapsed": 3}).json()
        assert "correct" in j and "answer" in j
        total = j["total"]
    r = teacher.post(f"/game/{code}/ket-thuc", follow_redirects=False)
    assert r.headers["location"].startswith(f"/bxh/{code}?ket_qua=")
    bxh = teacher.get(f"/bxh/{code}").text
    assert "Tèo" in bxh and "<td>4.3</td>" in bxh and str(total) in bxh and "🥇" in bxh
    teacher.post("/gv/dang-nhap", data={"pin": "9999"})
    assert "Tèo" in teacher.get(f"/gv/bxh/{quiz_id}").text


def test_game_khong_lo_dap_an_truoc_khi_tra_loi(teacher):
    quiz_id, code = _create_seed_quiz(teacher)
    teacher.post(f"/gv/de/{quiz_id}/trang-thai", data={"status": "published"})
    teacher.get("/gv/dang-xuat")
    teacher.post("/vao-bai", data={"code": code, "name": "Na 4.3"})
    page = teacher.get(f"/game/{code}").text
    assert "Tiếng chuông là thông tin" not in page  # giải thích/đáp án không có trong HTML
    j = teacher.post(f"/game/{code}/tra-loi", json={"question_id": 999999, "given": "A"}).json()
    assert "error" in j


def test_game_khong_cong_diem_hai_lan_mot_cau(teacher):
    quiz_id, code = _create_seed_quiz(teacher)
    teacher.post(f"/gv/de/{quiz_id}/trang-thai", data={"status": "published"})
    teacher.get("/gv/dang-xuat")
    teacher.post("/vao-bai", data={"code": code, "name": "Na 4.3"})
    teacher.get(f"/game/{code}")
    from services import quizzes as qz
    q = qz.get_quiz(quiz_id)["questions"][0]
    j1 = teacher.post(f"/game/{code}/tra-loi", json={"question_id": q["id"], "given": q["answer"], "elapsed": -5}).json()
    assert j1["correct"] and j1["points"] <= 160
    r = teacher.post(f"/game/{code}/tra-loi", json={"question_id": q["id"], "given": q["answer"], "elapsed": 1})
    assert r.status_code == 409
    r = teacher.post(f"/game/{code}/tra-loi", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_game_body_khong_phai_object_tra_400(teacher):
    quiz_id, code = _create_seed_quiz(teacher)
    teacher.post(f"/gv/de/{quiz_id}/trang-thai", data={"status": "published"})
    teacher.get("/gv/dang-xuat")
    teacher.post("/vao-bai", data={"code": code, "name": "Na 4.3"})
    teacher.get(f"/game/{code}")
    for body in ([1, 2], None, "x", 5):
        assert teacher.post(f"/game/{code}/tra-loi", json=body).status_code == 400


def test_choi_lai_game_tao_luot_moi_va_ket_thuc_hai_lan_khong_nhan_doi(teacher):
    quiz_id, code = _create_seed_quiz(teacher)
    teacher.post(f"/gv/de/{quiz_id}/trang-thai", data={"status": "published"})
    teacher.get("/gv/dang-xuat")
    teacher.post("/vao-bai", data={"code": code, "name": "Na 4.3"})
    from services import quizzes as qz, attempts as svc
    q = qz.get_quiz(quiz_id)["questions"][0]
    ids = []
    for _ in range(2):
        teacher.get(f"/game/{code}")
        teacher.post(f"/game/{code}/tra-loi", json={"question_id": q["id"], "given": q["answer"], "elapsed": 2})
        r = teacher.post(f"/game/{code}/ket-thuc", follow_redirects=False)
        ids.append(int(r.headers["location"].rsplit("=", 1)[1]))
    assert ids[0] != ids[1]
    r = teacher.post(f"/game/{code}/ket-thuc", follow_redirects=False)
    assert r.headers["location"] == "/"
    assert len(svc.quiz_report(quiz_id)["attempts"]) == 2


def test_trang_huong_dan_dung_ai_an_toan(app_client):
    page = app_client.get("/huong-dan")
    assert page.status_code == 200
    assert "AI cũng có thể sai" in page.text
    assert "Không nhập thông tin cá nhân" in page.text
    assert "Xin gợi ý" in page.text
    # Trang chủ và menu đều dẫn tới hướng dẫn để học sinh dễ thấy
    assert 'href="/huong-dan"' in app_client.get("/").text


def test_trang_gioi_thieu_san_pham_cong_khai(app_client):
    page = app_client.get("/gioi-thieu")
    assert page.status_code == 200
    assert "Trợ lý Tin học AI" in page.text and "chức năng" in page.text.lower()
    assert "/huong-dan" in page.text
    # Không lộ PIN giáo viên trên trang công khai
    assert "9999" not in page.text and "PIN" not in page.text
    assert app_client.get("/static/anh/hs-ket-qua.jpg").status_code == 200


def test_giao_vien_tu_dat_tieu_de_khi_tao_de(teacher):
    r = teacher.post("/gv/tao-de/sgk", data={"grade": "4", "lesson_ids": ["b1"], "n": "10", "title": "Ôn tập giữa kỳ I lớp 4.2"}, follow_redirects=False)
    quiz_id = int(r.headers["location"].rsplit("/", 1)[1])
    assert "Ôn tập giữa kỳ I lớp 4.2" in teacher.get(f"/gv/de/{quiz_id}").text
    # Đổi tên sau khi tạo
    teacher.post(f"/gv/de/{quiz_id}/tieu-de", data={"title": "Tên mới <b>"}, follow_redirects=False)
    page = teacher.get(f"/gv/de/{quiz_id}").text
    assert "Tên mới &lt;b&gt;" in page and "Ôn tập giữa kỳ I lớp 4.2" not in page


def test_gioi_thieu_co_so_lop_trien_khai(app_client):
    assert "15 lớp" in app_client.get("/gioi-thieu").text


def test_tai_de_ra_word_va_ban_dap_an(teacher):
    import io
    from docx import Document

    quiz_id, _ = _create_seed_quiz(teacher)
    r = teacher.get(f"/gv/de/{quiz_id}/word")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert r.content[:2] == b"PK"
    text = "\n".join(p.text for p in Document(io.BytesIO(r.content)).paragraphs)
    assert "Câu 1" in text and "Họ và tên" in text and "ĐÁP ÁN" not in text
    r2 = teacher.get(f"/gv/de/{quiz_id}/word?dap_an=1")
    text2 = "\n".join(p.text for p in Document(io.BytesIO(r2.content)).paragraphs)
    assert "ĐÁP ÁN" in text2


def test_tai_word_can_dang_nhap(app_client):
    r = app_client.get("/gv/de/1/word", follow_redirects=False)
    assert r.status_code == 303


def test_bang_xep_hang_hien_ca_lop_va_cot_lop(teacher):
    from services import attempts, quizzes

    quiz_id, code = _create_seed_quiz(teacher)
    teacher.post(f"/gv/de/{quiz_id}/trang-thai", data={"status": "published"})
    quiz = quizzes.get_quiz(quiz_id)
    for i in range(25):
        aid = attempts.create_game_attempt(quiz, f"Bạn{i} 4.{i % 3 + 1}", {})
        attempts.set_game_result(aid, 100 + i, 60)
    rows = attempts.leaderboard(quiz_id)
    assert len(rows) == 25
    assert rows[0]["lop"] == "4.1" and rows[0]["ten"] == "Bạn24"
    page = teacher.get(f"/gv/bxh/{quiz_id}").text
    assert "Bạn0" in page and "<th>Lớp</th>" in page


def test_game_co_nut_bat_tat_am_thanh(teacher):
    quiz_id, code = _create_seed_quiz(teacher)
    teacher.post(f"/gv/de/{quiz_id}/trang-thai", data={"status": "published"})
    teacher.post("/vao-bai", data={"code": code, "name": "Bi 4.3"})
    page = teacher.get(f"/game/{code}").text
    assert 'id="loa"' in page and 'id="nhac"' in page and "AudioContext" in page
