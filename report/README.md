# Báo cáo CO4031, nhóm 7, lớp L02

| File | Nội dung |
| --- | --- |
| `report.tex`, `report.pdf` | Báo cáo |
| `slides.tex`, `slides.pdf` | Slide dùng khi quay video |
| `video_plan.md` | Phân công và kịch bản quay |
| `make_submission.sh` | Đóng gói ZIP nộp LMS vào `report/dist/` |

Build PDF: `cd report && tectonic report.tex && tectonic slides.tex`
(`brew install tectonic`). Font Be Vietnam Pro nằm trong `fonts/` (SIL OFL).

Đóng gói: `report/make_submission.sh` tạo `report/dist/CO4031_Nhom7_L02.zip` gồm
`report.pdf`, `slides.pdf`, `src/` (mã nguồn tại commit hiện tại) và `data/` (dữ liệu mẫu).

Trước khi nộp: điền link video ở trang bìa `report.tex`, build lại, chạy script.
