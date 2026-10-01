# CoinSight: Crypto Data Warehouse & DSS

Kho dữ liệu và hệ hỗ trợ quyết định cho thị trường tiền điện tử. Code được chia
theo kiến trúc (pipeline, kho dữ liệu, API), không chia theo thư mục từng người.

## Phân công

```text
 A - STREAMING (Đại)
 [Kaggle replay] --\
                    >-> [Kafka] -> [Spark Structured Streaming] -> [Live metric 7 ngày]
 [Binance API] ----/       ^                                            |
                       [Kafka UI]                                       v
                                                                 [PostgreSQL DW]
 B - KHO DỮ LIỆU (Nhi)                                                  ^
 [Binance Public Data] -> [staging] -> [Kiểm tra DQ] -> [dw: star schema] -> [mart OLAP]
                          \_________ Airflow chạy mỗi ngày _________/

 C - DSS (Dương)
 [Lịch sử từ DW] -> [Forecast] --\
                                  >-> [FastAPI] <-> [Dashboard]
 [Live metric] ------------------/
```

| Phần | Người | Nội dung |
| --- | --- | --- |
| A | Đại | Binance/CSV replay, Kafka, Spark Streaming, live market aggregate |
| B | Nhi | Batch ETL, star schema PostgreSQL, data quality, OLAP/data mart, Airflow |
| C | Dương | Mô hình dự báo, kết hợp dự báo với live signal, FastAPI, dashboard |

Tài liệu chi tiết phần B: [`docs/phan_data_warehouse.md`](docs/phan_data_warehouse.md)
(tóm tắt cho nhóm) và [`docs/dw_design.md`](docs/dw_design.md) (thiết kế).

## Cấu trúc thư mục

```text
CoinSight/
|-- pipeline/            Producer replay/live, Spark stream job, extract và batch ETL
|-- postgres/init/       Schema, dữ liệu seed và mart; tự chạy khi tạo database mới
|-- postgres/queries/    Truy vấn OLAP mẫu (make olap)
|-- airflow/             Image và DAG Airflow
|-- app/                 FastAPI và dashboard
|-- tests/               Test contract, producer, kho dữ liệu và API
|-- docs/                Tài liệu và sơ đồ (EERD, lược đồ quan hệ)
|-- scripts/             Script sinh sơ đồ
|-- data/                Dữ liệu mẫu; data/raw/ chứa file tải về (không lên git)
|-- docker-compose.yml   Các service, volume và network
`-- Makefile             Lệnh tắt
```

Phần dự báo chưa được hiện thực.

## Cài đặt

Đã thử trên Linux; macOS tương tự, Windows nên dùng WSL2. Các lệnh chạy từ thư
mục gốc của repo.

| Công cụ | Để làm gì | Kiểm tra |
| --- | --- | --- |
| Docker và Docker Compose v2 | Chạy PostgreSQL, Kafka, Spark, Airflow, API | `docker compose version` |
| git | Lấy code | `git --version` |
| [uv](https://docs.astral.sh/uv/) | Tạo môi trường Python 3.12 cho các lệnh `make` | `uv --version` |
| make | Chạy lệnh tắt trong `Makefile` | `make --version` |
| DBeaver hoặc extension PostgreSQL của VS Code (tùy chọn) | Xem bảng bằng giao diện | |

Cần khoảng 70 MB cho dữ liệu Binance và vài GB cho Docker image (Kafka, Spark,
Airflow khoảng 1,5 GB).

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # nếu chưa có uv
export PATH="$HOME/.local/bin:$PATH"

git clone git@github.com:caoTayTang/CoinSight.git
cd CoinSight
cp .env.example .env
id -u                 # nếu khác 1000, sửa AIRFLOW_UID trong .env
make setup            # tạo .venv và cài thư viện Python
```

`.env` chứa giá trị nhìn **từ bên trong container** (host `postgres`, đường dẫn
`/data/...`). Các lệnh `make extract`, `make batch`, `make test` chạy trên máy
thật nên tự đổi sang `localhost` và đường dẫn trong repo; không cần sửa `.env`
cho chúng. `.env` không được đưa lên git.

Khi chạy script Python trực tiếp (không qua `make`), kích hoạt môi trường trước:

```bash
source .venv/bin/activate
```

## Chạy toàn bộ hệ thống

```bash
docker compose up --build -d
docker compose ps --all
```

Lệnh mặc định dùng nguồn replay từ Kaggle (container `producer`, không gọi
Binance). Lần đầu chạy lâu hơn vì Docker phải tải Kafka và Spark. `postgres`,
`kafka`, `kafka-ui`, `spark` và `api` phải ở trạng thái đang chạy; `pipeline`
và `producer` cuối cùng hiện `Exited (0)`, nghĩa là job chạy một lần đã xong.

| Cổng | Service | Địa chỉ |
| --- | --- | --- |
| 5432 | PostgreSQL | `localhost:5432` |
| 8000 | Dashboard và API (C) | <http://localhost:8000>, tài liệu API <http://localhost:8000/docs> |
| 8080 | Kafka UI (A) | <http://localhost:8080> |
| 8081 | Airflow (B), chạy bằng `make airflow` | <http://localhost:8081> |

Dashboard tóm tắt độ phủ dữ liệu của kho, giá và volume gần đây, thống kê mô tả
và live metric mới nhất từ Spark; tự làm mới mỗi 30 giây.

Kafka UI, Airflow và dashboard không có đăng nhập khi chạy local, và Kafka UI có
thể sửa topic. Không mở các cổng này trên máy dùng chung hoặc mạng công cộng.

Dừng service, giữ nguyên dữ liệu:

```bash
make down
```

## A - Streaming

- `pipeline/producer.py` replay dữ liệu OHLCV lịch sử vào Kafka theo thứ tự thời
  gian sự kiện; mặc định chọn BTC, ETH và SOL.
- `pipeline/live_producer.py` lấy nến 1 phút đã đóng từ API market-data công
  khai của Binance và gửi theo cùng định dạng sự kiện.
- `pipeline/stream_etl.py` kiểm tra và loại trùng sự kiện, tính metric cửa sổ
  trượt 7 ngày theo ngày, rồi upsert vào `fact_live_metric`.
- Kafbat UI hiển thị topic, partition, offset và nội dung message.
- Offset của Kafka và checkpoint của Spark cho phép stream chạy tiếp sau khi
  khởi động lại.

### Dữ liệu replay

Nguồn replay là dataset Kaggle
[Cryptocurrency Prices (Top 200+) - Daily Updated](https://www.kaggle.com/datasets/isaaclopgu/cryptocurrency-historical-prices-top-100-2025),
phiên bản 105: OHLCV theo ngày của 250 coin trong `Crypto_historical_data.csv`,
giấy phép CC BY-SA 4.0. Đặt file tại:

```text
data/raw/Crypto_historical_data.csv
```

Đổi `REPLAY_SYMBOLS` trong `.env` để chọn coin khác, hoặc để trống để replay tất
cả.

### Xem stream chạy

Chọn một nguồn. Replay lịch sử từ Kaggle:

```bash
make stream
```

Hoặc dữ liệu hiện tại của BTC, ETH, SOL từ Binance:

```bash
make live
```

Cả hai lệnh đều mở dashboard tại <http://localhost:8000>. Dòng trạng thái
`API connected` chỉ cho biết trang kết nối được FastAPI, không cho biết nguồn
stream nào đang chạy. Hai lệnh giữ terminal để hiện log; bấm `Ctrl+C` khi xong.

Live producer lấy 2 nến 1 phút mới nhất và gửi nến đã đóng gần nhất, qua
[endpoint market-data công khai](https://developers.binance.com/en/docs/binance-spot-api-docs/rest-api/market-data-endpoints#klinecandlestick-data)
của Binance nên không cần API key. `volume` là quote volume tính bằng USDT. Đổi
`LIVE_SYMBOLS` trong `.env` để dùng coin khác có cặp USDT.

Binance giới hạn request theo IP. Mỗi request kline có weight `2`; 3 coin mặc
định lấy mỗi 20 giây chỉ dùng `18` weight mỗi phút. Khi nhận HTTP `429` hoặc
`418`, producer tuân theo `Retry-After` của Binance và tạm dừng trước khi thử lại.

Không chạy `make stream` và `make live` cùng lúc trên checkpoint mới: sự kiện
live đẩy watermark theo thời gian sự kiện của Spark lên, làm các sự kiện replay
cũ bị coi là đến trễ. Để đổi chế độ và dựng lại toàn bộ trạng thái local (xóa
dữ liệu PostgreSQL local):

```bash
docker compose --profile live down --volumes
make live
```

Mở <http://localhost:8080> rồi chọn:

```text
local -> Topics -> crypto-prices -> Messages
```

Bấm vào một message để xem JSON. Các trường chính:

- `symbol`: mã coin, ví dụ `BTC`.
- `event_time`: ngày gốc trong dữ liệu lịch sử.
- `open_price`, `high_price`, `low_price`, `close_price`: giá của nến.
- `volume`: quote volume của nến.
- `event_id`: định danh ổn định Spark dùng để loại trùng.
- `source`: `kaggle-replay` hoặc `binance-rest`.

Topic có 3 partition. Offset chỉ là vị trí của message trong partition, không
phải giá hay thời gian.

Xem Spark đọc sự kiện và lưu metric:

```bash
docker compose logs --follow spark
```

Tìm dòng `stored ... metric updates from batch ...`; bấm `Ctrl+C` để thôi xem,
container vẫn chạy. Truy vấn các cửa sổ 7 ngày đã sinh:

```bash
docker compose exec postgres psql -U crypto -d crypto_dw -c \
"select symbol, count(*) as windows, max(event_count) as max_events
 from fact_live_metric group by symbol order by symbol;"
```

`max_events` phải đạt `7` vì mỗi cửa sổ đầy đủ chứa 7 sự kiện giá theo ngày.

Lần đầu Spark khởi động sẽ tải Kafka connector. Để replay lại từ trạng thái hoàn
toàn sạch, xóa cả volume database lẫn checkpoint rồi chạy lại:

```bash
docker compose --profile live down --volumes
make stream
```

## B - Kho dữ liệu

- `pipeline/extract_binance.py` tải nến USDT theo ngày và theo giờ từ
  [Binance Public Data](https://data.binance.vision), kiểm tra checksum SHA-256,
  cache trong `data/raw/binance/` và nạp vào `staging.stg_ohlcv`.
- `pipeline/batch_etl.py` chạy 12 rule chất lượng dữ liệu trên staging, loại
  dòng lỗi, upsert phần còn lại vào kho và làm mới các mart. Kết quả ghi trong
  `meta.etl_batch` và `meta.dq_result`.
- `postgres/init/` tạo các schema `staging`, `dw`, `mart`, `meta`. `dw` là
  galaxy schema: `fact_ohlcv_daily` và `fact_ohlcv_hourly` dùng chung
  `dim_asset`, `dim_date`, `dim_time`, `dim_source` với bảng live metric và
  forecast. View `mart.fact_price` giữ tương thích với API.
- `postgres/init/04_marts.sql` định nghĩa các mart OLAP dùng `ROLLUP`, `CUBE` và
  `GROUPING SETS`. `postgres/queries/olap_examples.sql` minh họa roll-up,
  drill-down, slice, dice và pivot.
- `airflow/dags/coinsight_warehouse.py` chạy pipeline lúc 03:00 UTC mỗi ngày:
  `extract_binance -> transform_load -> quality_report`.

### Dựng kho dữ liệu

```bash
docker compose up -d postgres      # tự tạo schema ở lần chạy đầu
make extract                       # tải dữ liệu Binance vào staging
make batch                         # kiểm tra chất lượng, nạp vào kho, làm mới mart
make olap                          # chạy 9 truy vấn OLAP mẫu
```

| Lệnh | Thời gian | Dòng cuối |
| --- | --- | --- |
| `make extract` lần đầu | khoảng 5 phút | `batch N: loaded ... rows into staging.stg_ohlcv` |
| `make extract` các lần sau | 1–2 phút, chỉ tải file mới | như trên |
| `make batch` | khoảng 30 giây | `batch N: read ..., rejected 0, accepted ... daily and ... hourly, ...` |

Lần nạp ngày 30/09/2026 có khoảng 1,18 triệu dòng; số dòng tăng mỗi ngày vì
Binance công bố thêm dữ liệu. File đã tải được giữ trong `data/raw/binance/`,
nên chạy lại không tải lại.

### Xem dữ liệu

Kết nối bằng DBeaver, VS Code hoặc `psql`:

| Trường | Giá trị |
| --- | --- |
| Host | `localhost` |
| Port | `5432` |
| Database | `crypto_dw` |
| User | `crypto` |
| Password | `crypto` |

```bash
psql postgresql://crypto:crypto@localhost:5432/crypto_dw
```

| Schema | Nội dung |
| --- | --- |
| `staging` | `stg_ohlcv`: dữ liệu vừa tải, chưa kiểm tra |
| `dw` | Bảng `dim_*` và `fact_*` |
| `mart` | View (`v_*`, `fact_price`) và materialized view (`mv_*`) để phân tích |
| `meta` | `etl_batch` (log mỗi lần chạy), `dq_result` (kết quả kiểm tra chất lượng) |
| `public` | Bỏ qua: bảng cũ nếu database được tạo trước khi đổi schema |

Trong DBeaver, materialized view nằm ở thư mục riêng `mart → Materialized
Views`. Trong `psql`: `\dt dw.*` liệt kê bảng, `\dv mart.*` liệt kê view,
`\dm mart.*` liệt kê materialized view.

### Chạy bằng Airflow

```bash
make airflow
```

Mở <http://localhost:8081>. DAG `coinsight_warehouse_daily` mặc định đang tắt:
bật công tắc cạnh tên DAG để chạy theo lịch, hoặc bấm ▶ để chạy ngay. Một lần
chạy mất khoảng 1–3 phút; log của task `quality_report` liệt kê kết quả kiểm
tra chất lượng. Airflow nằm trong profile `airflow` nên `docker compose up` không
khởi động nó. Metadata của Airflow nằm trong database riêng `airflow` trên cùng
server PostgreSQL, tự tạo ở lần chạy đầu.

### Biến cấu hình

| Biến | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | `crypto_dw`, `crypto`, `crypto` | Database và tài khoản; chỉ có hiệu lực khi tạo volume mới |
| `DATABASE_URL` | `postgresql://crypto:crypto@postgres:5432/crypto_dw` | Chuỗi kết nối cho các container |
| `BINANCE_DATA_URL` | `https://data.binance.vision` | Nơi tải file lịch sử |
| `BATCH_SYMBOLS` | 20 coin | Danh sách coin, phân tách bằng dấu phẩy, không có đuôi `USDT` |
| `BATCH_INTERVALS` | `1d,1h` | Loại nến: theo ngày và theo giờ |
| `BATCH_START_MONTH` | `2020-01` | Tháng đầu tiên tải về |
| `AIRFLOW_UID` | `1000` | User id trên máy thật mà Airflow dùng, để ghi được `data/raw` |

Các biến còn lại trong `.env.example` thuộc phần streaming (Kafka, replay, live).

Thêm coin: thêm mã vào `BATCH_SYMBOLS` và thêm tên, nhóm của coin vào
`postgres/init/03_seed.sql`; nếu không, coin vẫn được nạp nhưng tên là mã coin
và không có nhóm.

Chạy thử nhanh với ít dữ liệu:

```bash
cd pipeline
DATABASE_URL=postgresql://crypto:crypto@localhost:5432/crypto_dw \
  ../.venv/bin/python extract_binance.py --symbols BTC,ETH --intervals 1d --start 2025-01
```

## C - DSS

- Đưa kết quả batch và live ra qua API.
- Duy trì dashboard HTML/CSS/JavaScript do FastAPI phục vụ.
- Duy trì Docker Compose, kiểm tra service, test tích hợp và kịch bản demo.
- File hiện có: `app/api.py`, `app/static/`, `docker-compose.yml`,
  `tests/test_api.py`.

## Test

```bash
docker compose up -d postgres      # các test kho dữ liệu cần PostgreSQL
make test
```

Test kiểm tra validation, lọc và sắp xếp CSV, chuẩn hóa nến Binance, đọc file
Binance, nạp kho và rule chất lượng dữ liệu, mart OLAP, và API. Chạy đúng sẽ
báo `29 passed`. Nếu PostgreSQL chưa chạy, các test kho tự bỏ qua (`skipped`).

## Làm lại từ đầu

Cần khi database được tạo trước khi đổi schema (không có schema `dw`), hoặc khi
muốn xóa hết dữ liệu local:

```bash
docker compose --profile live --profile airflow down --volumes   # xóa dữ liệu PostgreSQL local
docker compose up -d postgres
make extract
make batch
```

`data/raw/` không bị xóa, nên `make extract` lần này nhanh.

## Lỗi thường gặp

| Lỗi | Nguyên nhân | Cách xử lý |
| --- | --- | --- |
| `could not translate host name "postgres"` | Chạy script Python trực tiếp trên máy thật, nên nó đọc `DATABASE_URL` của container trong `.env` | Dùng `make extract` / `make batch`, hoặc đặt `DATABASE_URL=...@localhost:5432/...` trước lệnh |
| `connection refused` ở cổng 5432 | PostgreSQL chưa chạy | `docker compose up -d postgres` |
| `make test` báo nhiều test `skipped` | PostgreSQL chưa chạy | Bật PostgreSQL rồi chạy lại |
| `port is already allocated` cho 5432 | Máy đã có PostgreSQL khác dùng cổng 5432 | Tắt PostgreSQL đó, hoặc đổi cổng bên trái trong `docker-compose.yml` (ví dụ `"5433:5432"`) và dùng cổng mới khi kết nối |
| `schema "staging" does not exist` hoặc `relation "staging.stg_ohlcv" does not exist` | Database cũ, tạo trước khi đổi schema | Làm lại từ đầu |
| `URLError`, `timed out` khi `make extract` | Mạng chập chờn; mỗi request đã tự thử lại 3 lần | Chạy lại; file đã tải được giữ trong cache |
| Airflow báo `Permission denied` với `data/raw` | `AIRFLOW_UID` khác user id trên máy | Đặt `AIRFLOW_UID` bằng kết quả `id -u`, rồi `make airflow` |
| `.venv/bin/python: No such file or directory` | Chưa tạo môi trường Python | `make setup` |
