# Kế hoạch quay video CO4031, nhóm 7, lớp L02

Yêu cầu của đề: video 10–15 phút, mọi thành viên xuất hiện và trình bày, hình và
tiếng rõ, upload YouTube (unlisted) hoặc Google Drive, link ghi ở trang bìa báo cáo.
Hạn nộp: 23:59 Chủ nhật 15/11/2026.

Mục tiêu: 13–14 phút. Mỗi người quay phần mình phụ trách, dùng chung `slides.pdf` (26 slide; slide nền cam là lúc chuyển sang demo).

## Phân công

Theo `docs/dw_design.md` và lịch sử commit:

| Người | Phụ trách trong dự án | Phần trong video |
| --- | --- | --- |
| Hà Bảo Nhi (2312496) | Thiết kế DW, ETL batch, kiểm tra chất lượng, OLAP mart, Airflow lịch nạp | Phần 2 |
| Lê Chí Đại (2310621) | Luồng trực tiếp Kafka/Spark, API, giao diện, agent, vận hành | Phần 1, 3 |
| Đào Quang Dương (2310579) | DSS: mô hình dự báo, đánh giá, chính sách paper trade | Phần 4 |
| Cả nhóm | Tự đánh giá, kết | Phần 5 |

## Kịch bản theo thời gian

| Thời gian | Người | Slide | Nội dung | Demo |
| --- | --- | --- | --- | --- |
| 0:00–1:30 | Đại | 1–4 | Giới thiệu nhóm và vai trò. Câu hỏi nghiệp vụ: "Quý vừa rồi nhóm coin nào tăng mạnh nhất, rủi ro nhất?". Kiến trúc tổng: batch + stream vào một kho. | Không |
| 1:30–6:30 | Nhi | 5–12 | Nguồn Binance archive. Bus matrix, galaxy schema, grain, dimension, SCD1. ETL: SHA-256, staging, 7 rule loại + 5 cảnh báo, upsert idempotent, nạp lại không đổi checksum. OLAP: ROLLUP, CUBE, GROUPING SETS. | Demo 1 (1:30) |
| 6:30–9:00 | Đại | 13–17 | Luồng trực tiếp Kafka → Spark → PostgreSQL → WebSocket. Airflow chạy hằng ngày, trạng thái Behind. Truy vết một con số về archive gốc. Agent đọc kho để trả lời. | Demo 2 (1:30) |
| 9:00–12:00 | Dương | 18–23 | DSS theo 3 pha Simon. Bài toán hướng giá ngày, cổng Brier so với baseline. Dự báo quantile GRU/LSTM, chính sách paper trade. Kết luận trung thực: lợi suất giờ gần như không dự báo được. | Demo 3 (1:00) |
| 12:00–13:30 | Cả nhóm | 24–26 | Số liệu kết quả. Mỗi người nói một hạn chế của phần mình và hướng sửa. Đại kết. | Không |

## Demo

Chạy trên máy local bằng `docker compose up -d`. Quay demo riêng rồi chèn vào, không
quay demo trực tiếp lúc nói.

### Demo 1: Nhi, kho dữ liệu

1. `make extract-daily DAY=<ngày đã đóng>` rồi `make batch`; quay phần log cuối.
2. psql: `select * from meta.warehouse_load_report order by batch_id desc limit 1;`
   chỉ ra staged = rejected + duplicate + accepted.
3. Chạy lại `make batch` cùng ngày: 0 dòng thay đổi (idempotent).
4. Truy vấn `mart.mv_category_performance` với `category = 'ALL'` và một quý; rồi
   `mart.v_top_movers` của quý gần nhất.
5. Mở tab Data trên dashboard: số dòng, độ phủ, nến thiếu.

### Demo 2: Đại, vận hành và giao diện

1. Dashboard <http://localhost:3000>: chọn BTC, chart nến phút đang chạy.
2. Kafka UI <http://localhost:8080>: topic có message mới.
3. Airflow: DAG `coinsight_warehouse_daily` lần chạy gần nhất xanh.
4. Chat với agent: "Quý 3/2026 nhóm coin nào tăng mạnh nhất?" Chỉ ra con số trong câu
   trả lời khớp với kết quả psql ở Demo 1.

### Demo 3: Dương, DSS

1. `GET /v1/model/evaluation`: Brier model so với baseline, quyết định accept/reject.
2. `GET /v1/assets/BTC/prediction`: `probability_up`, ngày input, ngày target.
3. Trên dashboard: tín hiệu, hoặc thông báo "Model below baseline. Signal withheld."
   và giải thích vì sao hệ thống từ chối công bố.
4. Biểu đồ dự báo giá và khoảng q10–q90 từ báo cáo test của GRU/LSTM.

## Cách quay

- Mỗi người: OBS, 1920×1080, 30 fps. Màn hình slide toàn khung, webcam góc phải dưới.
- Mic rời hoặc tai nghe có mic; phòng yên tĩnh; quay thử 20 giây, nghe lại trước khi quay thật.
- Mỗi phần một file: `p1_dai.mp4`, `p2_nhi.mp4`, `demo1_nhi.mp4`, ... Quay lỗi thì quay lại cả slide đó, không cắt giữa câu.
- Phần 5: mỗi người quay đoạn 20–30 giây của mình; Đại ghép.
- Trước khi quay terminal: không mở `.env`, xoá lịch sử shell trên màn hình, ẩn thông báo, tăng cỡ chữ terminal lên 18pt.
- Đại dựng video (DaVinci Resolve hoặc CapCut), chèn tên người ở góc dưới khi đổi phần.

## Lịch

| Ngày | Việc | Ai |
| --- | --- | --- |
| Thứ Năm 12/11 | Đọc slide, sửa nội dung phần mình, điền MSSV và tên nhóm | Cả nhóm |
| Thứ Sáu 13/11 | Quay phần trình bày và demo | Mỗi người |
| Thứ Bảy 14/11 | Ghép, kiểm tra thời lượng ≤ 15 phút, upload unlisted | Đại |
| Thứ Bảy 14/11 | Điền link video vào bìa, build lại `report.pdf` | Nhi |
| Chủ nhật 15/11 | Nén ZIP: `report.pdf`, `slides.pdf`, link repo `src/`, link dữ liệu mẫu `data/`; nộp LMS trước 22:00 | Dương |

## Lời nói gợi ý

Nói theo ý, đừng đọc nguyên văn. Mỗi slide khoảng 20 tới 40 giây.

Đại mở đầu: "Nhóm chọn dữ liệu nến giá crypto của Binance. Có hai câu hỏi: quý vừa rồi
nhóm coin nào tăng mạnh nhất, và hôm nay có nên tin vào tín hiệu tăng giá không. Kho dữ liệu
trả lời câu đầu, DSS trả lời câu sau."

Nhi vào phần: "Em sẽ đi theo một cây nến BTC ngày 24/10, từ lúc nó là một dòng trong file ZIP
tới lúc nó nằm trong con số tổng của quý 4."

Đại vào phần 3: "Kho được nạp mỗi sáng. Phần này nói chuyện giữ cho nó chạy đúng, và cách người
dùng hỏi nó."

Dương vào phần: "Kho cho biết chuyện đã xảy ra. DSS thử đoán chuyện sắp xảy ra, và phải biết
lúc nào nên im lặng."

Kết: mỗi người một câu về hạn chế phần mình (xem mục 9 báo cáo), Đại cảm ơn thầy.
