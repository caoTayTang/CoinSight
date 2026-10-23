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
giao diện, Kafka UI và Jaeger. Airflow cần bật riêng.
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

## 4. Bật và theo dõi dữ liệu trực tiếp

Luồng live dùng để xem **trạng thái thị trường hiện tại**, không thay thế chart lịch sử
và không phải đầu vào của model ngày. Giao diện Market hiển thị nó ở khối **Live feed**:
một biểu đồ nến 1 phút riêng, cập nhật khi API WebSocket nhận snapshot mới. Danh sách
live trong `pipeline/settings.yaml` được đồng bộ với danh sách batch để mỗi asset trong
rail có thể có nến 1 phút sau khi producer/Spark chạy.

### 4.1. Chạy live stack

Nếu đã chạy `docker compose up --build -d` thì các service live mặc định đã được bật:
`kafka`, `live-producer`, `spark`, `api`, `frontend`. Nếu chỉ muốn bật riêng đường live:

```bash
make live
# hoặc
docker compose up --build -d kafka kafka-ui live-producer spark api frontend
```

### 4.2. Kiểm tra dữ liệu live đi qua từng bước

```bash
docker compose ps live-producer spark api frontend
docker compose logs --tail=100 live-producer spark
curl -s http://localhost:8000/v1/assets/BTC/live-summary
```

Mở Kafka UI tại <http://localhost:8080> và xem topic `crypto-prices-live`.

Nến chỉ xuất hiện sau khi phút đóng, event đi qua Binance WebSocket → Kafka → Spark →
PostgreSQL → API WebSocket → trình duyệt. Lúc vừa thêm coin vào cấu hình hoặc vừa
khởi động, một coin có thể hiện “Waiting for at least two closed one-minute candles”
cho tới khi có ít nhất hai nến 1 phút đã đóng được ghi DB. Kết nối API WebSocket thành
công chỉ chứng minh browser đã nối được API; muốn biết feed thật đang chạy thì kiểm
`fact_candle_minute_live` hoặc Kafka UI.

```sql
select symbol, open_time, close_price, volume_quote, kafka_offset
from dw.fact_candle_minute_live
where symbol = 'BTC'
order by open_time desc
limit 10;
```

### 4.3. Nếu biểu đồ live chưa chạy

- `live-producer` chưa Up: kiểm mạng ra Binance và log container.
- `spark` chưa Up hoặc lỗi package Kafka: xem `docker compose logs spark`.
- Kafka có message nhưng DB chưa có dòng: kiểm Spark và `DATABASE_URL`.
- DB có dòng nhưng UI chưa đổi: mở DevTools, kiểm WebSocket `/api/v1/assets/BTC/stream`.
- UI báo `502 Bad Gateway` sau khi recreate API: rebuild/recreate frontend để Nginx nhận lại địa chỉ API, hoặc dùng cấu hình Nginx có Docker DNS resolver hiện tại.
- Vừa khởi động xong hoặc vừa mở rộng danh sách live symbols: đợi ít nhất hai nến 1 phút kế tiếp đóng.

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

Nếu UI ghi **“Model below baseline. Signal withheld.”**, đó là trạng thái đúng: model ngày
hiện tại bị từ chối vì không vượt baseline theo điều kiện công bố, nên dashboard không hiển
thị tín hiệu giao dịch. Cần chạy `make dss-train` với dữ liệu warehouse đủ tốt và chỉ
`make dss-predict` khi artifact được chấp nhận.

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

Đặt key cho router (`GROQ_API_KEY`, tùy chọn `OPENROUTER_API_KEY`, `AWS_REGION` + `AWS_BEARER_TOKEN_BEDROCK`) theo `.env.example`.
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

## Agent extension và điều khiển riêng

Core Compose không tự thay thế hai stack protocol. Từ root repo, với artifacts đã chuẩn bị:

```bash
# Frozen model tools, A2A peers và prospective ledger
docker compose -p coinsight-agents -f compose.agents.yml up --build -d
# Trade/SRE, router và gateway
docker compose --env-file .env -f warehouse_agents/compose.yml up --build -d
```

Ports: forecast MCP 8010, forecast/MAD A2A 8011/8012; reasoning MCP 8020, Trade/SRE 8021/8022. Dừng bằng `down` với đúng compose/project, không xóa volumes. Bundle/model prerequisites và semantics nằm ở [agent contracts](agent_contracts.md) và [model integration](model_integration.md). Home-server networking khác laptop: dùng [home server](home_server.md).

Hướng dẫn đăng nhập ở [Google/GitHub setup](auth_setup.md); không chép OAuth client secrets vào `.env`. Đổi key/URL runtime phải recreate service liên quan.
