# Trợ lý Tin học AI

Web giúp giáo viên Tin học tiểu học (lớp 3-5, SGK Kết nối tri thức) tạo đề từ sách bằng AI, học sinh làm bài tại nhà, chấm tự động, gợi ý từng bước và kế hoạch ôn tập cá nhân.

## Chạy tại máy
```bash
cd app && python -m venv .venv && .venv/bin/pip install -r requirements.txt
export GEMINI_API_KEY=...   # bỏ qua nếu chỉ chạy bộ câu hỏi mẫu
export TEACHER_PIN=1234
.venv/bin/uvicorn main:app --reload
```
Giáo viên: /gv · Học sinh: /

## Biến môi trường
| Tên | Ý nghĩa |
|---|---|
| GEMINI_API_KEY | Khóa Google AI Studio (miễn phí). Không có thì chạy chế độ mẫu |
| GEMINI_API_KEYS | Nhiều khóa cách nhau bằng dấu phẩy để xoay vòng khi hết hạn mức |
| GEMINI_MODEL | mặc định gemini-3.5-flash |
| TEACHER_PIN | mã PIN vào khu vực giáo viên |
| SECRET_KEY | khóa ký cookie, đặt chuỗi ngẫu nhiên khi chạy thật |
| APP_DATA_DIR | thư mục lưu CSDL và tệp tải lên (Railway: /data trên volume) |

## Kiểm thử
```bash
APP_DATA_DIR=/tmp/tro-ly-test .venv/bin/pytest -q --cov=.
```
