# CoinSight: dữ liệu đi từ Binance đến đâu?

Tài liệu này giải thích **code hiện tại** bằng một ví dụ, rồi mới nêu contract. Contract là lời hứa ở ranh giới giữa hai bước: bước sau được nhận những trường nào, đơn vị gì, một dòng đại diện cho điều gì, và khi chạy lại có bị nhân đôi không. Nếu code thay đổi những lời hứa này, phải sửa tài liệu và migration tương ứng.

## Bắt đầu từ một nến BTCUSDT

`BTCUSDT` là cặp giao dịch Spot: `BTC` là coin cơ sở, `USDT` là đơn vị báo giá. `close_price = 86_000` nghĩa là giá đóng nến của **1 BTC là 86.000 USDT**; không nên ghi là USD. Một *nến* (candle/OHLCV) tóm tắt giao dịch trong một khoảng thời gian:

| Trường | Nghĩa |
| --- | --- |
| `open_time` | Đầu khoảng thời gian, theo UTC |
| `open_price`, `high_price`, `low_price`, `close_price` | Giá mở, cao nhất, thấp nhất, đóng |
| `volume_base` | Số BTC giao dịch trong khoảng đó |
| `volume_quote` | Giá trị giao dịch tính bằng USDT |
| `interval` | Độ dài khoảng: `1d`, `1h` hoặc `1m` |

Ví dụ nến `BTCUSDT` mở lúc `2026-10-04 00:00 UTC`, interval `1d`, mô tả **cả ngày UTC 04/10**. Nến `1h` mở cùng lúc chỉ mô tả giờ đầu tiên. Trong một ngày đủ dữ liệu sẽ có **1 nến `1d` và 24 nến `1h`** cho mỗi cặp.

CoinSight lấy dữ liệu Binance bằng hai đường. Chúng có mục đích khác nhau:

```text
LỊCH SỬ:  Binance ZIP (1d, 1h) → staging → kiểm tra → warehouse → DSS/API
REALTIME: Binance WebSocket (1m đã đóng) → Kafka → Spark → bảng live → API
                              └─ REST lấy bù nến 1m bị lỡ khi mất kết nối
```

Warehouse lịch sử nạp danh sách coin trong `batch.symbols` của `pipeline/settings.yaml` (mặc định 20 coin). Live dùng `live.symbols` (mặc định BTC, ETH, SOL). Model DSS dùng `dss.symbols` (hiện là BTC, ETH, SOL). Đây là **phạm vi mỗi pipeline**, không phải Binance chỉ có ba cặp.

## Đường lịch sử: ZIP → staging → warehouse

**Chặng 1 — Binance → file ZIP.** [ingest_binance_history.py](../pipeline/batch/ingest_binance_history.py) tải archive nến `1d`/`1h`, đọc file `.CHECKSUM` của Binance và kiểm SHA-256. Lần đầu có thể tải archive tháng để bootstrap; DAG hằng ngày chỉ kiểm archive của **ngày UTC đã kết thúc hôm qua**. `meta.source_file_manifest` ghi tên file, URL, SHA-256, coin, interval và số dòng. File ZIP trong `data/raw/` là cache, **không phải bảng warehouse**.

**Contract sau chặng 1:** file hợp lệ, đúng cặp `<symbol>USDT`, đúng interval và UTC. Với archive ngày, code yêu cầu 1 dòng `1d` hoặc 24 dòng `1h`. Thiếu file hoặc sai số dòng thì task thất bại; nó không tự bịa nến còn thiếu.

**Chặng 2 — ZIP → `staging.stg_ohlcv`.** Extractor mở CSV trong ZIP và ghi từng nến vào bảng tạm *staging*. Một dòng giữ `source_code='binance'`, `symbol='BTC'`, `candle_interval='1d'/'1h'`, `open_time`, OHLC, hai loại volume, `batch_id`, `source_file`. `batch_id` cho biết lần extract nào tạo dòng đó. Staging là nơi **chuẩn bị và kiểm tra**, chưa phải dữ liệu phân tích đã chấp nhận.

**Chặng 3 — staging → `dw`.** [warehouse_loader.py](../pipeline/batch/warehouse_loader.py) kiểm dữ liệu: giá dương, OHLC hợp lý, timestamp đúng giờ/ngày, v.v. Dòng sai bị loại và ghi lý do vào `meta.dq_result`; nếu tỷ lệ sai vượt ngưỡng thì cả load thất bại. Dòng hợp lệ được *upsert* vào:

| Bảng | Một dòng đại diện cho | Khóa không nhân đôi |
| --- | --- | --- |
| `dw.fact_ohlcv_daily` | Một coin, một ngày UTC, một nguồn | `asset_key + date_key + source_key` |
| `dw.fact_ohlcv_hourly` | Một coin, một giờ UTC, một nguồn | `asset_key + date_key + time_key + source_key` |

`asset_key`, `date_key`, `time_key`, `source_key` nối sang các bảng `dw.dim_*` để biết coin nào, ngày/giờ nào, nguồn nào. *Fact* chứa số đo; *dimension* chứa mô tả. `meta.batch_dependency` nối batch load với batch extract; `meta.loaded_archive` đánh dấu file **đã nạp thành công**, dựa trên checksum. Chạy lại cùng archive không thêm nến trùng. Archive được Binance sửa sẽ được nạp lại bằng upsert. Airflow [coinsight_warehouse.py](../airflow/dags/coinsight_warehouse.py) gọi các bước này lúc **06:00 UTC hằng ngày**; Airflow là bộ lên lịch/điều phối, không trực tiếp biến đổi từng nến.

Xem một nến đã vào warehouse trong DataGrip:

```sql
select a.symbol, d.full_date, f.open_price, f.close_price,
       f.volume_base, f.volume_quote, f.batch_id
from dw.fact_ohlcv_daily f
join dw.dim_asset a using (asset_key)
join dw.dim_date d using (date_key)
where a.symbol = 'BTC'
order by d.full_date desc
limit 5;
```

Lấy `batch_id` của một dòng rồi mở `GET /v1/lineage/batches/{batch_id}` trong API docs để lần ngược tới ZIP và SHA-256.

## Đường realtime: WebSocket → Kafka → Spark → bảng live

**Chặng 1 — Binance WebSocket → event.** [binance_live_client.py](../pipeline/stream/binance_live_client.py) nghe nến `1m`, nhưng **chỉ gửi khi nến đã đóng** (`k.x = true`). Nếu mất kết nối, nó dùng Binance REST để lấy bù các nến phút bỏ lỡ. WebSocket và REST cùng dùng `event_id` ổn định cho cùng một cặp và phút, ví dụ `binance:spot:BTCUSDT:1m:<open_time>`.

**Contract event v1:** `schema_version=1`, `pair='BTCUSDT'`, `symbol='BTC'`, `quote_asset='USDT'`, `interval='1m'`, thời điểm mở/đóng UTC, OHLC giá USDT, `volume_base`, `volume` là quote volume USDT, `source` (`binance-ws` hoặc `binance-rest-backfill`) và `mode='live'`. Producer gửi event vào Kafka với key là cặp giao dịch. Kafka giữ luồng sự kiện để Spark đọc; nó không phải bảng phân tích cho DataGrip.

**Chặng 2 — Kafka → Spark → PostgreSQL.** [spark_stream_processor.py](../pipeline/stream/spark_stream_processor.py) đọc topic Kafka, lọc event không hợp lệ, rồi ghi nến vào `dw.fact_candle_minute_live`. Một dòng là **một cặp + một phút mở nến**; bảng lưu thêm Kafka topic/partition/offset để truy lại event. Nếu REST gửi lại cùng nến, khóa `(pair, open_time)` ngăn nhân đôi. Spark cũng tiếp tục ghi metric cửa sổ 7 ngày cũ để dashboard cũ hoạt động.

API `GET /v1/assets/BTC/live-summary` đọc **15 phút đã đóng gần nhất** từ bảng nến phút: giá đóng mới nhất, % thay đổi, quote volume, có bao nhiêu trong 15 nến, và dữ liệu cũ bao nhiêu giây. Nếu mới có 7 nến thì báo **7/15**, không giả vờ đủ 15.

Xem dòng live gần nhất trong DataGrip:

```sql
select pair, open_time, close_price, volume_quote,
       transport, kafka_topic, kafka_partition, kafka_offset
from dw.fact_candle_minute_live
where symbol = 'BTC'
order by open_time desc
limit 5;
```

## DSS: warehouse → đánh giá model → dự đoán

Contract DSS/API đã chốt cho Dương ở [dss_contract_v1.md](dss_contract_v1.md).
Phần dưới giải thích cách code hiện tại tạo feature và đánh giá; tài liệu handoff
quy định grain, trạng thái API và điều kiện publish.

[DSS code](../pipeline/decision/direction_model.py) hiện thử một câu hỏi cụ thể: **“Giá đóng nến ngày mai có cao hơn giá đóng nến hôm nay không?”** Đây là phân loại tăng/không tăng trong **ngày UTC kế tiếp**, không phải dự báo giá bao nhiêu USDT, và không phải tín hiệu mua/bán tự động. Một model dùng chung BTC, ETH, SOL; feature lấy từ nến ngày và 24 nến giờ **đã đóng**. Nến phút realtime không đi vào model này.

Code chia dữ liệu theo thời gian: quá khứ để train, 30 ngày tiếp theo để validation, 30 ngày cuối để test. Nó so xác suất của logistic regression với *baseline* đơn giản (tỷ lệ ngày tăng trong tập train). Chỉ khi điểm **Brier** của model thấp hơn baseline ở cả validation và test thì model mới được công bố. Brier thấp hơn là tốt hơn. Mỗi lần đánh giá được ghi vào `meta.model_evaluation`.

**Trạng thái khi kiểm tra ngày 05/10/2026:** model thử nghiệm bị `rejected` vì Brier validation khoảng `0,2636`, kém baseline khoảng `0,2560`. Do đó `dw.dim_model`/`dw.fact_direction_prediction` chưa có model và dự đoán được chấp nhận; API prediction trả `insufficient_data`. Đây là quyết định có chủ ý, không phải lỗi API. Airflow [coinsight_dss.py](../airflow/dags/coinsight_dss.py) thử train lại thứ Hai và chạy bước suy luận lúc **07:30 UTC hằng ngày**. Câu hỏi/nhãn v1 hiện được cố định trong contract DSS; Dương có thể cải thiện model theo contract đó.

Xem kết quả đánh giá:

```sql
select evaluated_at, decision, validation_brier,
       baseline_validation_brier, test_brier, baseline_test_brier
from meta.model_evaluation
order by evaluation_id desc
limit 5;
```

## API và agent nhận gì?

[app/api.py](../app/api.py) **đọc** các bảng trên và trả JSON. Endpoint v1 luôn có:

- `status`: `ready`, `stale`, `insufficient_data` hoặc `unavailable`;
- `data`: kết quả, hoặc `null` nếu chưa có;
- `provenance`: nguồn, độ hạt dữ liệu, thời điểm quan sát/tính, batch/model nếu có;
- `quality`: độ mới, số mẫu, cảnh báo;
- `trace_id`: ID của response.

Thử `GET /v1/assets/BTC/snapshot` (lịch sử), `GET /v1/assets/BTC/live-summary` (realtime), `GET /v1/model/evaluation` (model), và `GET /v1/data-status` trong `http://localhost:8000/docs`. Browser kết nối `WS /v1/assets/BTC/stream`: nhận ngay `live.snapshot` gồm hai API envelope `summary` và `metric`, rồi nhận bản mới sau mỗi commit Spark; `heartbeat` không chứa giá mới. [Agent](../app/chat_agent.py) là phần tuỳ chọn: khi Bedrock credential hợp lệ, nó chỉ gọi bốn tool **đọc** snapshot, live summary, prediction và model evaluation; nó không được chạy SQL tự do.

## Điều chưa hoàn thành

Đây là bản chạy local, **chưa phải production**: chưa deploy ra subdomain, chưa có xác suất dự đoán được model chấp nhận, chưa có retention cho bảng phút, cảnh báo vận hành, auth cho API công khai, hay trace được lưu xuyên suốt một cuộc chat agent. UI React hiện ở `frontend/`. File [deployment.md](deployment.md) ghi các điều kiện còn thiếu để deploy.

### Assistant request diagnostics (additive)

`POST /v1/agent/chat` keeps `answer`, `tools_used`, `model_id` and adds optional
`trace`: `trace_id` (32-hex OpenTelemetry ID when enabled, otherwise request UUID), `duration_ms`, `input_tokens`, `output_tokens`,
`model_calls`, `events[]` with `kind`, `name`, `status`, `duration_ms`.
Usage sums provider-reported input/output counts over successful model calls;
it is not billing or total-cost accounting. Failed provider calls may have
unknown usage. HTTP errors include `X-Trace-ID` and a reference in `detail`.
Server JSON log event `assistant.request` correlates success/failure with the ID.
No prompts, answers, credentials or raw tool payloads are included in this log.
This does not provide persistent tracing, metrics/alerts, or per-claim citations.
