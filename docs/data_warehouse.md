# Bản ghi tiến độ Data Warehouse ban đầu (Nhi)

Đây là snapshot phần DW ban đầu; một số số liệu, lịch chạy và câu hỏi phân công
bên dưới đã cũ. Trạng thái chạy hiện tại ở [README](../README.md), contract dữ
liệu ở [data_contracts_v1.md](data_contracts_v1.md), contract DSS/API đã chốt
cho Dương ở [dss_contract_v1.md](dss_contract_v1.md).

Tài liệu này tóm tắt phần Nhi phụ trách và những gì thay đổi với phần của Đại
và Dương. Chi tiết kỹ thuật
(ERD, grain, rule DQ, lý do thiết kế) nằm trong [`dw_design.md`](dw_design.md).

Code đã được đưa vào repo hiện tại. Cách cài đặt, cấu hình và xử lý lỗi:
[`README.md`](../README.md).

## 1. Phần của Nhi làm gì

Nhi xây **kho dữ liệu lịch sử**: lấy dữ liệu giá crypto, làm sạch, lưu theo
star schema trong PostgreSQL, rồi tổng hợp sẵn để phân tích. Đại lo dữ liệu
**mới nhất** (streaming); Dương dùng **lịch sử** từ kho để train model và
hiển thị dashboard.

```text
                         ┌─────────────── Nhi ────────────────┐
Binance Public Data ──►  staging ──► kiểm tra DQ ──► dw (star) ──► mart (OLAP)
(file lịch sử)           └──────── Airflow chạy mỗi ngày ─────┘        │
                                                      │                 │
Binance API ──► Kafka ──► Spark ──► fact_live_metric  │   (Đại)         │
                                                      ▼                 ▼
                                         FastAPI + dashboard + forecast (Dương)
```

Ba phần dùng chung bảng `dim_asset` (danh sách coin) và `dim_date` (lịch),
nên dữ liệu lịch sử, live và dự báo join được với nhau.

## 2. Đã xong

| Thành phần | File | Kết quả |
| --- | --- | --- |
| Nguồn dữ liệu | `pipeline/batch/ingest_binance_history.py` | 20 coin, 01/2020 – 28/09/2026, có kiểm tra checksum |
| Schema | `postgres/init/01`–`03_*.sql` | Galaxy schema: 4 dimension, 2 fact của Nhi, giữ nguyên 2 fact của Đại và Dương |
| ETL + kiểm tra chất lượng | `pipeline/batch/warehouse_loader.py` | 1.179.705 dòng; 12 rule DQ; chạy lại không tạo trùng |
| OLAP | `postgres/init/04_marts.sql`, `postgres/queries/olap_examples.sql` | 5 mart dùng `ROLLUP`, `CUBE`, `GROUPING SETS`; 9 truy vấn mẫu |
| Lập lịch | `airflow/dags/coinsight_warehouse.py` | Hiện chạy 06:00 UTC mỗi ngày |
| Tài liệu, sơ đồ | `README.md`, `docs/`, `scripts/generate_diagrams.py` | Hướng dẫn cài đặt, thiết kế chi tiết, EERD Chen, lược đồ quan hệ |
| Test | `tests/batch/test_warehouse_loader.py`, `tests/batch/test_ingest_binance_history.py` | 29 test pass (gồm test cũ) |

### Dữ liệu

- **Nguồn**: [Binance Public Data](https://data.binance.vision), file chính
  thức do Binance công bố, miễn phí, không cần tài khoản. Chọn nguồn này vì
  phần streaming của Đại cũng lấy từ Binance, nên mã coin, đơn vị volume và
  múi giờ (UTC) khớp nhau.
- **Quy mô**: 47.212 dòng theo ngày + 1.132.493 dòng theo giờ.
- **Coin**: BTC, ETH, BNB, SOL, XRP, ADA, DOGE, TRX, AVAX, LINK, DOT, LTC, BCH,
  UNI, ATOM, XLM, ETC, FIL, NEAR, SHIB.

### Bảng chính

| Bảng | Một dòng là | Ghi chú |
| --- | --- | --- |
| `dw.fact_ohlcv_daily` | 1 coin × 1 ngày | Giá mở, cao, thấp, đóng (OHLC) và volume |
| `dw.fact_ohlcv_hourly` | 1 coin × 1 giờ | Như trên, theo giờ |
| `dw.dim_asset` | 1 coin | Mã (`BTC`), tên, nhóm (layer-1, meme, payments...) |
| `dw.dim_date` | 1 ngày | Thứ, tuần, tháng, quý, năm, cuối tuần |
| `dw.dim_time` | 1 giờ (0–23) | Buổi trong ngày, phiên Á/Âu/Mỹ |
| `dw.dim_source` | 1 nguồn | `binance`, `kaggle`, `binance-rest` |

### Kiểm tra chất lượng dữ liệu

Mỗi lần nạp, 7 rule loại dòng lỗi (giá ≤ 0, high < low, sai mốc giờ...) và 5
rule cảnh báo (trùng, thiếu nến, dữ liệu cũ...). Nếu hơn 5% số dòng bị loại,
cả lần nạp bị hủy và kho giữ nguyên. Kết quả lưu trong `meta.dq_result`.

Lần nạp gần nhất: không dòng nào bị loại; cảnh báo 58 nến không có giao dịch,
258 chỗ thiếu nến (Binance bảo trì) và 18 ngày volume ngày lệch tổng volume giờ
hơn 1%.

### Mart OLAP

| Mart | Dùng để |
| --- | --- |
| `mart.v_daily_return` | Return từng ngày của từng coin |
| `mart.mv_asset_period_summary` | Hiệu suất theo tháng → quý → năm (roll-up, drill-down) |
| `mart.mv_category_performance` | So sánh nhóm coin theo năm, quý (slice, dice) |
| `mart.mv_hourly_activity` | Hoạt động theo giờ và phiên giao dịch |
| `mart.v_top_movers` | 3 coin tăng, giảm mạnh nhất mỗi quý |

## 3. Thay đổi ảnh hưởng tới phần của các bạn

Không cần sửa code của hai bạn. Nhi đã chạy thử các câu SQL mà
`spark_stream_processor.py` dùng (ghi `dim_asset`, `fact_live_metric`) và các endpoint
`/assets`, `/overview` của API trên schema mới; chưa chạy lại toàn bộ job
Spark streaming, nhờ Đại kiểm tra lại sau khi merge.

**Đại (streaming)**

- `spark_stream_processor.py` chạy nguyên như cũ. `dim_asset` và `fact_live_metric` giờ
  nằm trong schema `dw`, nhưng database đặt `search_path` nên tên bảng không
  kèm schema vẫn đúng.
- `fact_live_metric` giữ nguyên cấu trúc.
- `docker-compose.yml` có thêm service `airflow` trong profile riêng:
  `docker compose up` **không** khởi động nó. Airflow dùng cổng 8081 vì 8080
  là Kafka UI.

**Dương (API, dashboard, forecast)**

- API vẫn đọc `fact_price`, nay là view `mart.fact_price` lấy **giá đóng cửa
  theo ngày** từ kho. Dashboard hiển thị đủ 20 coin, đã kiểm tra.
- DSS hiện ghi `dw.fact_direction_prediction` và `dw.dim_model`; xem
  [contract DSS](dss_contract_v1.md). `fact_forecast` là ý tưởng cũ.
- Các mart ở mục 2 đọc được ngay bằng SQL nếu muốn đưa lên dashboard.

**Database đã tồn tại:** Compose chạy service `migrate` trước API/Spark.
Không cần xóa volume để nhận schema mới; `down --volumes` sẽ mất dữ liệu local.

## 4. Quyết định hiện hành cho các phần liên quan

- Coin dùng mã `BTC` trong warehouse, cặp giao dịch live là `BTCUSDT`; thời
  gian theo UTC, giá và quote volume tính bằng USDT.
- DW lịch sử giữ nến `1d` và `1h` cho 20 coin. Live 1 phút ở bảng riêng.
- DSS v1 phân loại hướng **ngày kế tiếp** cho BTC/ETH/SOL; output là xác suất
  trong `dw.fact_direction_prediction` chỉ khi model thắng baseline. Handoff ở
  [dss_contract_v1.md](dss_contract_v1.md).

## 5. Chạy thử

```bash
make test         # cần Postgres đang chạy để test kho không bị skip
make olap         # chạy 9 truy vấn OLAP mẫu
make airflow      # mở http://localhost:8081, bật DAG coinsight_warehouse_daily
```

## 6. Việc còn lại của Nhi

| Việc | Khi nào |
| --- | --- |
| Kiểm tra độ phủ 24 giờ/ngày và 180 ngày/coin cho DSS | Trước khi publish model |
| Trình bày chất lượng dữ liệu và lineage trong demo | Trước buổi báo cáo |
| Dữ liệu mẫu nhỏ để nộp kèm (`data/`) | Trước 15/11 |
| Báo cáo phần DW, slide, demo | 09/11 – 15/11 |
