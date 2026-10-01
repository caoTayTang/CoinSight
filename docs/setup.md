# Cài đặt và chạy kho dữ liệu

Hướng dẫn dựng phần Data Warehouse trên một máy mới, từ lúc clone đến lúc xem
được dữ liệu và chạy Airflow. Các lệnh chạy từ thư mục gốc của repo. Đã thử
trên Linux; macOS tương tự, Windows nên dùng WSL2.

## 1. Cần cài trước

| Công cụ | Để làm gì | Kiểm tra |
| --- | --- | --- |
| Docker và Docker Compose v2 | Chạy PostgreSQL, Airflow và các service khác | `docker compose version` |
| git | Lấy code | `git --version` |
| [uv](https://docs.astral.sh/uv/) | Tạo môi trường Python 3.12 cho các lệnh `make` | `uv --version` |
| make | Chạy các lệnh tắt trong `Makefile` | `make --version` |
| DBeaver hoặc extension PostgreSQL của VS Code (tùy chọn) | Xem bảng bằng giao diện | |

Cài uv nếu chưa có:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

Dung lượng cần: khoảng 70 MB cho file dữ liệu Binance, vài GB cho các Docker
image (Airflow khoảng 1,5 GB).

## 2. Lấy code và tạo file cấu hình

```bash
git clone git@github.com:caoTayTang/CoinSight.git
cd CoinSight
git switch nhi/data-warehouse      # cho tới khi nhánh được merge vào main
cp .env.example .env
id -u                              # nếu khác 1000, sửa AIRFLOW_UID trong .env
make setup                         # tạo .venv và cài thư viện Python
```

`.env` chứa giá trị nhìn **từ bên trong container** (host `postgres`, đường dẫn
`/data/...`). Các lệnh `make extract`, `make batch`, `make test` chạy trên máy
thật nên tự đổi sang `localhost` và đường dẫn trong repo; không cần sửa `.env`
cho chúng. `.env` không được đưa lên git.

## 3. Dựng kho dữ liệu

```bash
docker compose up -d postgres      # PostgreSQL, tự tạo schema ở lần chạy đầu
make extract                       # tải dữ liệu Binance vào staging
make batch                         # kiểm tra chất lượng, nạp vào kho, làm mới mart
make olap                          # chạy 9 truy vấn OLAP mẫu
make test                          # 29 test
```

Kết quả mong đợi:

| Lệnh | Thời gian | Dòng cuối |
| --- | --- | --- |
| `make extract` lần đầu | khoảng 5 phút | `batch N: loaded 1180705 rows into staging.stg_ohlcv` |
| `make extract` các lần sau | 1–2 phút, chỉ tải file mới | như trên, số dòng tăng theo ngày |
| `make batch` | khoảng 30 giây | `batch N: read ..., rejected 0, accepted ... daily and ... hourly, ...` |
| `make test` | vài giây | `29 passed` |

File tải về được cache trong `data/raw/binance/`, nên chạy lại không tải lại.
Số dòng tăng mỗi ngày vì Binance công bố thêm dữ liệu.

## 4. Xem dữ liệu

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
Views`, không nằm trong `Tables` hay `Views`. Trong `psql`: `\dt dw.*` liệt
kê bảng, `\dv mart.*` liệt kê view, `\dm mart.*` liệt kê materialized view.

## 5. Chạy bằng Airflow

```bash
make airflow                       # build và chạy Airflow cùng PostgreSQL
```

Mở <http://localhost:8081> (không cần đăng nhập khi chạy local). DAG
`coinsight_warehouse_daily` mặc định đang tắt: bật công tắc bên cạnh tên DAG
để chạy theo lịch 03:00 UTC mỗi ngày, hoặc bấm nút ▶ để chạy ngay. Một lần
chạy mất khoảng 1–3 phút; log của task `quality_report` liệt kê kết quả
kiểm tra chất lượng.

Airflow nằm trong profile `airflow`, nên `docker compose up` thường không
khởi động nó. Dừng tất cả bằng `make down`.

## 6. Biến cấu hình

Các biến trong `.env` mà phần kho dữ liệu dùng. Biến của phần streaming được
mô tả trong `README.md`.

| Biến | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | `crypto_dw`, `crypto`, `crypto` | Database và tài khoản PostgreSQL; chỉ có hiệu lực khi tạo volume mới |
| `DATABASE_URL` | `postgresql://crypto:crypto@postgres:5432/crypto_dw` | Chuỗi kết nối cho các container |
| `BINANCE_DATA_URL` | `https://data.binance.vision` | Nơi tải file lịch sử |
| `BATCH_SYMBOLS` | 20 coin | Danh sách coin, phân tách bằng dấu phẩy, không có đuôi `USDT` |
| `BATCH_INTERVALS` | `1d,1h` | Loại nến: theo ngày và theo giờ |
| `BATCH_START_MONTH` | `2020-01` | Tháng đầu tiên tải về |
| `AIRFLOW_UID` | `1000` | User id trên máy thật mà Airflow chạy dưới tên đó, để ghi được `data/raw` |

Thêm coin mới: thêm mã vào `BATCH_SYMBOLS`, rồi thêm tên và nhóm của coin vào
`postgres/init/03_seed.sql`; nếu không, coin vẫn được nạp nhưng tên là mã
coin và không có nhóm.

Muốn chạy thử nhanh với ít dữ liệu, gọi script trực tiếp với tham số:

```bash
cd pipeline
DATABASE_URL=postgresql://crypto:crypto@localhost:5432/crypto_dw \
  ../.venv/bin/python extract_binance.py --symbols BTC,ETH --intervals 1d --start 2025-01
```

## 7. Cổng đang dùng

| Cổng | Service |
| --- | --- |
| 5432 | PostgreSQL |
| 8000 | API và dashboard (Dương) |
| 8080 | Kafka UI (Đại) |
| 8081 | Airflow |

## 8. Làm lại từ đầu

Cần làm khi database được tạo trước khi đổi schema (không có schema `dw`), hoặc
khi muốn xóa hết dữ liệu local:

```bash
docker compose --profile live --profile airflow down --volumes   # xóa dữ liệu PostgreSQL local
docker compose up -d postgres
make extract
make batch
```

`data/raw/binance/` không bị xóa, nên `make extract` lần này nhanh.

## 9. Lỗi thường gặp

| Lỗi | Nguyên nhân | Cách xử lý |
| --- | --- | --- |
| `could not translate host name "postgres"` | Chạy script Python trực tiếp trên máy thật, nên nó đọc `DATABASE_URL` của container trong `.env` | Dùng `make extract` / `make batch`, hoặc đặt `DATABASE_URL=...@localhost:5432/...` trước lệnh |
| `connection refused` ở cổng 5432 | PostgreSQL chưa chạy | `docker compose up -d postgres` |
| `make test` báo nhiều test `skipped` | PostgreSQL chưa chạy, các test kho tự bỏ qua | Bật PostgreSQL rồi chạy lại |
| `port is already allocated` cho 5432 | Máy đã có PostgreSQL khác dùng cổng 5432 | Tắt PostgreSQL đó, hoặc đổi cổng bên trái trong `docker-compose.yml` (ví dụ `"5433:5432"`) và dùng cổng mới khi kết nối |
| `schema "staging" does not exist` hoặc `relation "staging.stg_ohlcv" does not exist` | Database cũ, tạo trước khi đổi schema | Làm lại từ đầu (mục 8) |
| `URLError`, `timed out` khi `make extract` | Mạng chập chờn; mỗi request đã tự thử lại 3 lần | Chạy lại; file đã tải được giữ trong cache |
| Airflow báo `Permission denied` với `data/raw` | `AIRFLOW_UID` khác user id trên máy | Đặt `AIRFLOW_UID` bằng kết quả `id -u`, rồi `make airflow` |
| `.venv/bin/python: No such file or directory` | Chưa tạo môi trường Python | `make setup` |
