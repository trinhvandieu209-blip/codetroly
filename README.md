# Trợ lý Tin học AI

Web giúp giáo viên Tin học tiểu học (lớp 3, 4, 5) soạn đề từ sách giáo khoa bằng AI, cho học sinh làm bài, chấm tự động, gợi ý từng bước khi sai và lập kế hoạch ôn tập riêng cho từng em. Sản phẩm dự thi Giải thưởng Tiên phong Ứng dụng AI trong Giáo dục Việt Nam 2026 của thầy Trịnh Văn Điệu, Trường Liên cấp TH-THCS Nguyễn Quốc Phú.

Web đang chạy: https://tro-ly-tin-hoc-ai-production.up.railway.app
Mô tả chức năng: https://tro-ly-tin-hoc-ai-production.up.railway.app/gioi-thieu

## Tính năng
- Giáo viên chọn bài trong sách hoặc tải tài liệu riêng, AI (Google Gemini) soạn đề trắc nghiệm, câu ngắn, câu nối ghép.
- Giáo viên duyệt, sửa, đặt tên đề rồi phát hành bằng mã bài 6 ký tự; tải đề ra Word để in.
- Học sinh vào bằng mã bài và tên gọi, không cần tài khoản. Chấm ngay, gợi ý tối đa 3 mức không lộ đáp án, kế hoạch ôn 3 ngày.
- Chế độ game: mỗi câu 20 giây, điểm thưởng tốc độ và chuỗi đúng, bảng xếp hạng cả lớp, âm thanh và nhạc nền.
- Báo cáo lớp, tải CSV. Trang hướng dẫn học sinh dùng AI an toàn.
- Vẫn chạy bằng bộ câu hỏi mẫu khi không có khóa AI.

## Công nghệ
Python 3.10, FastAPI, SQLite, Jinja2, Google Gemini (google-genai), python-docx. Triển khai bằng Docker trên Railway.

## Chạy thử trên máy
```bash
cd app
python -m venv .venv && .venv/bin/pip install -r requirements.txt
export TEACHER_PIN=1234 SECRET_KEY=$(python -c "import secrets;print(secrets.token_hex(32))")
export GEMINI_API_KEY=...   # bỏ qua dòng này để chạy chế độ câu hỏi mẫu
.venv/bin/uvicorn main:app --reload
```
Mở http://localhost:8000. Khu vực giáo viên ở `/gv`.

Kiểm thử: `cd app && .venv/bin/python -m pytest -q`

## Biến môi trường
| Biến | Ý nghĩa |
|---|---|
| `TEACHER_PIN` | Mã vào khu vực giáo viên (4–8 số) |
| `SECRET_KEY` | Khóa ký phiên, ít nhất 32 ký tự |
| `GEMINI_API_KEY` hoặc `GEMINI_API_KEYS` | Khóa Gemini, nhiều khóa cách nhau bằng dấu phẩy |
| `APP_DATA_DIR` | Thư mục lưu CSDL và tệp tải lên |
| `TRUST_PROXY` | Đặt `1` khi chạy sau proxy (Railway) |

## Lưu ý
Kho này không chứa sách giáo khoa quét (bản quyền), dữ liệu học sinh hay khóa API. Chế độ soạn đề từ sách cần giáo viên tự đặt file PDF sách vào thư mục `tailieu/` theo `app/data/sgk_index.json`.

## Giấy phép
Mã nguồn dùng cho mục đích giáo dục. Liên hệ: trinhvandieu209@gmail.com
