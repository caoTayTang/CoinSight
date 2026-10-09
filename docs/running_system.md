# Chạy và kiểm tra hệ thống

Trang này giữ toàn bộ hướng dẫn thao tác. Để hiểu nguyên lý, đọc
[Luồng dữ liệu](data_flow.md); để xem việc chưa hoàn thành, đọc
[Tiến độ](product_readiness.md).

## 1. Chuẩn bị

Cần Docker Compose v2, Git, `make`, `uv` và Python 3.12 cho lệnh chạy trên máy.
Chạy từ thư mục gốc repo. Node 22 dùng khi phát triển giao diện.

```bash
cp .env.example .env  # chỉ lần đầu, không ghi đè cấu hình đã có
make setup           # tạo .venv và cài thư viện Python
```

`pipeline/settings.yaml` chứa coin, interval, lịch và ngưỡng xử lý. `.env` chứa
kết nối, đường dẫn và thông tin AWS/Bedrock. Không ghi thành công `.env`.

## 2. Khởi động

```bash
docker compose up --build -d
docker compose ps --all
```

`--build` yêu cầu build image trước khi chạy; Docker vẫn tận dụng cache.
Không có tùy chọn đó, Compose dùng image đã tồn tại và chỉ build khi cần tạo image
lần đầu. Sau khi sửa mã nguồn được đóng gói trong image, dùng `--build` để cập nhật.

Mặc định có PostgreSQL, migration, Kafka, producer Binance, Spark, API,
giao diện, Kafka UI và Jaeger. Airflow và replay Kaggle cần bật riêng.
`migrate` chạy một lượt rồi thoát với mã 0; các service xử lý liên tục cần ở trạng thái Up.

| Công cụ | Địa chỉ |
| --- | --- |
| Bảng theo dõi và tài liệu | http://localhost:3000 và http://localhost:3000/docs/ |
| API và mô tả đường dẫn API | http://localhost:8000/docs |
| Kafka UI | http://localhost:8080 |
| Airflow, sau khi bật | http://localhost:8081 |
| Jaeger | http://localhost:16686 |
| PostgreSQL | localhost:5432 |

## 3. Nạp lịch sử

```bash
make extract  # ZIP → staging theo settings.yaml
make batch    # kiểm tra → warehouse → mart
make olap     # chạy truy vấn OLAP mẫu
```

Hai lệnh đầu chạy một lượt rồi kết thúc. Lần đầu có thể tải nhiều archive do
`batch.start_month` mặc định là 2020-01 và có 20 coin.
Thử một ngày UTC đã được Binance công bố:

```bash
make extract-daily DAY=2026-10-04
make batch
curl -s http://localhost:8000/v1/data-status
```

Nạp bù lịch sử chỉ BTC theo giờ từ 2024, nếu nhóm chọn phạm vi nhỏ hơn:

```bash
DATABASE_URL=postgresql://crypto:crypto@localhost:5432/crypto_dw RAW_DIR=data/raw \
  .venv/bin/python -m pipeline.batch.ingest_binance_history --symbols BTC --intervals 1h --start 2024-01
make batch
```

Lệnh minh họa chưa có nghĩa đã chạy nạp bù lịch sử. Ranh thời gian huấn luyện vẫn cần
cập nhật trong giao ước dự báo giờ trước khi dùng phạm vi này.

## 4. Theo dõi dữ liệu trực tiếp

```bash
docker compose logs --tail=100 live-producer spark
curl -s http://localhost:8000/v1/assets/BTC/live-summary
```

Nến chỉ xuất hiện sau khi phút đóng và Spark ghi DB. Lúc vừa khởi động, số nến
trong cửa sổ 15 phút có thể chưa đủ. Kết nối WebSocket thành công chưa chứng minh
nến mới đang tới. Mở Kafka UI để xem topic `crypto-prices-live`, partition và message.

## 5. Airflow và mô hình hiện tại

```bash
make airflow
```

Mở Airflow rồi bật DAG `coinsight_warehouse_daily` và `coinsight_direction_daily`.
Container scheduler chạy liên tục, task chỉ chạy theo từng lượt. Lịch cụ thể được
mô tả một lần tại [Luồng dữ liệu](data_flow.md#5-mô-hình-và-điều-phối).

```bash
make dss-demo     # dữ liệu tổng hợp; không ghi dự đoán vào DB
make dss-train    # dữ liệu warehouse thật, daily classifier
make dss-predict  # cần artifact được chấp nhận
```

Các lệnh trên chưa huấn luyện XGBoost dự báo giờ. Giao ước riêng của nó ở
[dự báo giờ](hourly_forecast_contract.md).

## 6. Xem PostgreSQL trong DataGrip

Cấu hình local mặc định: host `localhost`, port `5432`, database `crypto_dw`,
user/password `crypto`. Nếu đã sửa `.env`, dùng giá trị của bạn.

```sql
select pair, open_time, close_price, volume_quote, kafka_offset
from dw.fact_candle_minute_live
where symbol = 'BTC'
order by open_time desc
limit 10;
```

Đợi phút tiếp theo để so mốc thời gian và số dòng. Bảng trực tiếp lưu nến phút, không phải
mọi lần giá đổi. Kiểm tra lịch sử giờ:

```sql
select a.symbol, count(*), min(f.open_time), max(f.open_time)
from dw.fact_ohlcv_hourly f
join dw.dim_asset a using (asset_key)
group by a.symbol;
```

Tìm lần nạp và lỗi chất lượng tại `meta.etl_batch` và `meta.dq_result`.

## 7. Bedrock

Đặt `AWS_REGION`, `BEDROCK_MODEL_ID` và credentials hợp lệ theo `.env.example`.
Mô hình phải khả dụng cho tài khoản/vùng đã chọn. Sau khi sửa `.env`, tạo lại API:

```bash
docker compose up -d --force-recreate api frontend
```

Xem lỗi bằng `docker compose logs --tail=100 api`, rồi tìm trace ID trong Jaeger.
Không dán credentials vào log, tài liệu hay ghi thành công.

## 8. Kiểm tra mã nguồn

```bash
make test                       # PostgreSQL cần chạy cho test warehouse
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
docker compose config --quiet
```

Tập kiểm tra PostgreSQL dùng database kiểm thử riêng. Nếu server không truy cập được,
các tập kiểm tra đó có thể bị bỏ qua; xem số lượng skipped trước khi kết luận đạt.

## 9. Dừng, chạy lại và migration

```bash
make down
```

Dữ liệu PostgreSQL, Kafka và checkpoint còn trong named volume. ZIP nằm trên đĩa
máy trong `data/raw/`, tệp mô hình local trong `data/models/`.
Chạy lại không tự nhân đôi fact theo khóa; audit record của job có thể tăng.
DB đã có dữ liệu nâng schema qua `docker compose up -d migrate`.
Chỉ dùng `docker compose down --volumes` khi chủ động muốn xoá named volumes.

## 10. Lỗi thường gặp

| Lỗi | Cách xử lý |
| --- | --- |
| Không có `.venv/bin/python` | Chạy `make setup` |
| Host `postgres` không tìm thấy khi chạy Python trên máy | Dùng Make mục tiêu hoặc `DATABASE_URL` trỏ localhost |
| Không kết nối được 5432 | Kiểm tra PostgreSQL và cổng bị chiếm |
| Thiếu bảng/schema sau cập nhật mã nguồn | Chạy migration, kiểm tra log `migrate` |
| Airflow không ghi được `data/raw` | Đặt `AIRFLOW_UID` theo `id -u` |
| API proxy trả 502 sau khi tạo lại API | Hiện có thể cần restart giao diện; cải thiện DNS môi trường chạy còn trong danh sách việc cần làm |
| Producer có log nhưng UI chưa có giá | Xem Spark, DB và mốc thời gian; Kafka có event chưa có nghĩa DB đã được ghi |
