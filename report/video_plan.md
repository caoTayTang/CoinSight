# Kế hoạch quay video CO4031, nhóm 7, lớp L02

Yêu cầu của đề: video 10–15 phút, mọi thành viên xuất hiện và trình bày, hình và
tiếng rõ, upload YouTube (unlisted) hoặc Google Drive, link ghi ở trang bìa báo cáo.
Hạn nộp: 23:59 Chủ nhật 15/11/2026.

Mục tiêu: khoảng 13 phút 45 giây. Mỗi người nói liền một phần, không xen kẽ: Nhi, rồi Đại, rồi Dương.
Dùng chung `slides.pdf` (26 slide; slide nền cam là lúc chuyển sang demo).

## Phân công

| Người | Slide | Nội dung | UI trong demo |
| --- | --- | --- | --- |
| Hà Bảo Nhi (2312496) | 1–10 | Mở đầu, kiến trúc, thiết kế kho, ETL và kiểm tra chất lượng | Airflow, psql, tab Data |
| Lê Chí Đại (2310621) | 11–17 | Nạp lại idempotent, OLAP, luồng trực tiếp, vận hành, agent | Airflow, psql, Kafka UI, dashboard, agent, Jaeger |
| Đào Quang Dương (2310579) | 18–26 | DSS, mô hình dự báo, cổng công bố, kết quả, hạn chế, kết | Swagger UI, dashboard tab Signal |

Phần nạp lại và OLAP (slide 12–13) chuyển từ Nhi sang Đại cho cân thời lượng.

## Kịch bản theo thời gian

| Thời gian | Người | Slide | Nội dung | Demo |
| --- | --- | --- | --- | --- |
| 0:00–1:15 | Nhi | 1–4 | Giới thiệu nhóm. Câu hỏi nghiệp vụ: "Quý vừa rồi nhóm coin nào tăng mạnh nhất?" và "ngày mai có nên tin tín hiệu tăng giá không". Kiến trúc: batch và stream vào một kho. | Không |
| 1:15–3:00 | Nhi | 5–9 | Nguồn Binance archive. Bus matrix, galaxy schema, grain, dimension, SCD1. ETL: SHA-256, staging, 7 rule loại + 5 cảnh báo. | Không |
| 3:00–4:15 | Nhi | 10 | | Demo 1 |
| 4:15–6:30 | Đại | 11–16 | Upsert idempotent, nạp lại không đổi checksum. CUBE trả lời câu hỏi mở đầu. Luồng Kafka → Spark → PostgreSQL → WebSocket. Airflow hằng ngày, truy vết một con số. Agent hỏi kho. | Không |
| 6:30–8:30 | Đại | 17 | | Demo 2 |
| 8:30–11:30 | Dương | 18–22 | DSS theo 3 pha Simon. Hướng giá ngày, cổng Brier so với baseline. Dự báo quantile GRU/LSTM, paper trade. Kết quả âm: lợi suất giờ gần như không dự báo được. | Không |
| 11:30–12:30 | Dương | 23 | | Demo 3 |
| 12:30–13:45 | Dương | 24–26 | Số liệu kho, hạn chế của cả ba phần và hướng sửa, cảm ơn thầy. | Không |

## Demo trên hệ thống đã deploy

Quay trên server nhà, không dựng lại ở máy local: server có đủ lịch sử, lịch chạy Airflow, ledger dự báo và
luồng trực tiếp. Dashboard công khai: <https://coinsight.kaiosthefox.dpdns.org>.

Các UI khác chỉ nghe trên `127.0.0.1` của server. Mở đường hầm SSH trước khi quay, giữ terminal này mở:

```bash
ssh -N home \
  -L 5432:127.0.0.1:5432 \
  -L 8000:127.0.0.1:8000 \
  -L 8080:127.0.0.1:8080 \
  -L 8081:127.0.0.1:8081 \
  -L 16686:127.0.0.1:16686
```

| UI | Địa chỉ trên máy mình |
| --- | --- |
| psql | `psql postgresql://crypto:crypto@localhost:5432/crypto_dw` |
| Airflow | <http://localhost:8081> |
| Kafka UI | <http://localhost:8080> |
| Swagger UI (API) | <http://localhost:8000/docs> |
| Jaeger | <http://localhost:16686> |

Nếu máy mình đã có Postgres hoặc dịch vụ khác chiếm cổng, đổi số bên trái, ví dụ `-L 15432:127.0.0.1:5432`.
Ai chưa có quyền SSH qua Cloudflare Access thì nhờ Đại mở đường hầm và quay chung màn hình.

Không chạy `make` trên host server bằng root (sự cố 22/10). Mọi thao tác nạp đi qua Airflow UI.

### Demo 1: Nhi, kho dữ liệu (1:15)

1. Airflow: mở DAG `coinsight_warehouse_daily`, tab Graph: `extract_binance` → `transform_load` →
   `quality_report`. Mở lần chạy gần nhất.
2. Log của `quality_report`: 12 rule, số dòng bị loại, cảnh báo.
3. psql: `select * from meta.warehouse_load_report order by batch_id desc limit 5;`
   chỉ ra staged = rejected + duplicate + accepted.
4. psql: `\dt dw.*`, rồi một cây nến BTC trong `dw.fact_ohlcv_daily` nối `dim_asset`, `dim_date`.
5. Dashboard, tab Data: số dòng, độ phủ, nến thiếu.

### Demo 2: Đại, OLAP, luồng trực tiếp và agent (2:00)

1. Airflow: clear lần chạy gần nhất để nạp lại cùng ngày. psql: lần nạp mới có `changed_rows` = 0.
2. psql: `mart.mv_category_performance` với `category = 'ALL'` của một quý, rồi `mart.v_top_movers`.
3. Kafka UI: topic `crypto-prices-live` có message mới. Dashboard: chọn BTC, nến phút đang chạy.
4. Đăng nhập, hỏi agent: "Quý 3/2026 nhóm coin nào tăng mạnh nhất?" So con số với kết quả bước 2.
5. Jaeger: tìm trace của câu hỏi vừa rồi, mở từng span tool và câu SQL.

### Demo 3: Dương, DSS (1:00)

1. Swagger UI: `GET /v1/model/evaluation`, Brier mô hình so với baseline, quyết định accept/reject.
2. Swagger UI: `GET /v1/assets/BTC/prediction`: `probability_up`, ngày input, ngày target.
3. Dashboard, tab Signal: tín hiệu, hoặc "Model below baseline. Signal withheld." và lý do hệ thống từ chối công bố.
4. Biểu đồ giá và khoảng q10–q90 từ báo cáo test của GRU/LSTM.
5. Tùy chọn: chạy một policy backtest BTC trên dashboard. Chỉ làm khi đã chép snapshot gốc
   `20261022T000000Z-9e078a41301d` (BTC) và `20261023T000000Z-eab401ad1ed3` (ETH) từ máy Dương lên
   `data/forecasting/snapshots/` trên server; thiếu snapshot thì backtest báo lỗi.

## Trước khi quay

- [ ] Khôi phục project Supabase (đang pause); không có thì agent chỉ cho khách hỏi 5 câu.
- [ ] Dọn đĩa server (đang 92%).
- [ ] Mỗi người mở thử đường hầm SSH và các UI của phần mình.
- [ ] Dương: gửi hai thư mục snapshot nếu muốn demo backtest.

## Cách quay

- Mỗi người: OBS, 1920×1080, 30 fps. Màn hình slide toàn khung, webcam góc phải dưới.
- Mic rời hoặc tai nghe có mic; phòng yên tĩnh; quay thử 20 giây, nghe lại trước khi quay thật.
- Mỗi người một file liền mạch gồm slide và demo: `p1_nhi.mp4`, `p2_dai.mp4`, `p3_duong.mp4`. Quay lỗi thì quay lại cả slide đó, không cắt giữa câu.
- Trước khi quay terminal: không mở `.env`, xoá lịch sử shell trên màn hình, ẩn thông báo, tăng cỡ chữ terminal lên 18pt. Trình duyệt: ẩn thanh bookmark.
- Đại dựng video (DaVinci Resolve hoặc CapCut), chèn tên người ở góc dưới khi đổi phần.

## Lịch

| Ngày | Việc | Ai |
| --- | --- | --- |
| Thứ Bảy 14/11 | Đọc slide phần mình, thử đường hầm SSH và UI | Mỗi người |
| Thứ Bảy 14/11 | Quay phần trình bày và demo | Mỗi người |
| Chủ nhật 15/11 sáng | Ghép, kiểm tra thời lượng ≤ 15 phút, upload unlisted | Đại |
| Chủ nhật 15/11 trưa | Điền link video vào bìa, build lại `report.pdf` | Nhi |
| Chủ nhật 15/11 | Chạy `report/make_submission.sh`, nộp ZIP lên LMS trước 22:00 | Dương |

## Lời nói gợi ý

Nói theo ý, đừng đọc nguyên văn. Mỗi slide khoảng 20 tới 40 giây.

Nhi mở đầu: "Nhóm chọn dữ liệu nến giá crypto của Binance. Có hai câu hỏi: quý vừa rồi nhóm coin nào
tăng mạnh nhất, và hôm nay có nên tin vào tín hiệu tăng giá không. Kho dữ liệu trả lời câu đầu, DSS trả lời câu sau."

Nhi vào phần kho: "Em sẽ đi theo một cây nến BTC ngày 24/10, từ lúc nó là một dòng trong file ZIP tới lúc nó
nằm trong bảng fact."

Đại vào phần: "Dữ liệu đã vào kho. Phần này nói chuyện nạp lại cho an toàn, dùng kho để trả lời câu hỏi mở đầu,
và giữ hệ thống chạy đúng mỗi ngày."

Dương vào phần: "Kho cho biết chuyện đã xảy ra. DSS thử đoán chuyện sắp xảy ra, và phải biết lúc nào nên im lặng."

Dương kết: đọc nhanh hạn chế của ba phần trên slide 25, cảm ơn thầy.
