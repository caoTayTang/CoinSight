# Contract forecasting giờ — CoinSight

Trạng thái: **chốt làm cơ sở triển khai trên nhánh `feature/hourly-forecast-contract`**,
09/10/2026. Đây là quyết định triển khai theo yêu cầu của chủ project, chưa phải
xác nhận review của Dương. API/model mô tả dưới đây **chưa được implement**.
Proposal gốc: [forecasting_design.md](forecasting_design.md).
Daily classifier và [contract hiện tại](dss_contract_v1.md) tiếp tục độc lập.

## 1. Bài toán và model đầu tiên

Sau khi một nến Spot Binance `1h` đóng, dự báo log-return của nến kế tiếp:

```text
y[t] = ln(close[t+1] / close[t])
forecast_close_usdt = close[t] × exp(predicted_log_return)
```

- Coin được hỗ trợ trong contract: BTC, ETH, SOL; triển khai và train **BTC trước**.
- Một model riêng cho mỗi coin. Horizon cố định một giờ, quote currency USDT.
- Model đầu tiên: **XGBoost `XGBRegressor`**, CPU, không pretrained.
- Hai baseline bắt buộc: zero-return và mean của 24 log-return gần nhất.
- Không biến predicted return thành `probability_up`; regression không xuất xác suất.
- Không có mua/bán tự động, khoảng tin cậy hoặc đảm bảo lợi nhuận trong contract này.

XGBoost được chọn để thử toàn bộ dataset → evaluation → artifact trước khi thêm
deep learning. GRU/LSTM/PatchTST/iTransformer giữ trong backlog nghiên cứu.

## 2. Các mốc thời gian — tất cả UTC

Dùng khoảng thời gian nửa mở `[open_time, close_boundary)`; không dùng giây cuối
`xx:59:59` làm ranh giới vì độ chính xác timestamp của nguồn có thể khác nhau.

| Field | Định nghĩa | Ví dụ |
| --- | --- | --- |
| `input_open_time` | Giờ mở của nến cuối cùng dùng làm input, tức `t` | 10:00 |
| `cutoff_time` | `input_open_time + 1h`; input chỉ gồm nến đóng không muộn hơn mốc này | 11:00 |
| `generated_at` | Thời điểm inference thực sự hoàn tất | 11:02 |
| `target_open_time` | `cutoff_time`; giờ mở nến cần dự báo | 11:00 |
| `target_close_time` | `cutoff_time + 1h` | 12:00 |

Ví dụ trên dùng nến `[10:00,11:00)` để dự báo giá đóng của `[11:00,12:00)`.
`cutoff_time` **không phải** timestamp của lần chạy job và **không phải** giờ mở input.

Online inference chỉ được công bố nếu `0 <= generated_at - cutoff_time <= 5 phút`,
nến input đã commit và mọi feature hợp lệ. Quá 5 phút trả `stale`, không tạo
forecast mới mang danh hiện tại. Forecast đã công bố hết hiệu lực khi
`now >= target_close_time`; lịch sử vẫn được giữ để chấm điểm.
Mốc 5 phút là SLA ban đầu của project, không phải tính chất của Binance.

## 3. Warehouse → dataset

Nguồn train: `dw.fact_ohlcv_hourly`, join `dw.dim_asset` và `dw.dim_source`, chỉ
`source_code='binance'`. Khóa tự nhiên: `(source, symbol, open_time)`.

Các cột cần có: `open_time`, OHLC, `volume_quote`, `trade_count`, `batch_id`,
`loaded_at`. Giá và quote volume tính theo USDT; không gọi là USD.

Điều kiện nhận dữ liệu:

- Giờ mở nằm đúng ranh giờ UTC, khóa không trùng; duplicate làm snapshot fail.
- OHLC hữu hạn, dương; high/low bao được open và close.
- Quote volume hữu hạn, không âm; trade count nguyên, không âm, không null.
- Chỉ nến đã đóng tại thời điểm extract snapshot.
- Sort theo coin/thời gian, reindex theo lưới giờ. Không forward-fill, interpolate
  hoặc impute nến thiếu. Sample cắt qua gap/row không hợp lệ bị loại và đếm lý do.

### Chốt lookback và warm-up

Sequence có **168 feature rows** tại `t-167 … t`. Để tính return/volume-change
của row đầu tiên, phải có thêm nến `t-168`: tổng **169 nến raw liên tiếp**.
Label cần nến `t+1`, nên sample train cần 170 nến liên tiếp `t-168 … t+1`.
Inference cần 169 nến; không được yêu cầu hay đọc target chưa tồn tại.

Giới hạn chung cho mọi model: không dùng raw input trước `t-168`.
XGBoost dùng lag `0,1,2,3,6,12,24,48,72,167`; **bỏ lag 168 của return** vì
nó cần thêm nến `t-169`, vượt giới hạn. Momentum 168 vẫn hợp lệ: `ln(C[t]/C[t-168])`.

13 feature gốc theo proposal: log-return, open-close return, high-low range,
close position, upper/lower wick, log quote volume, volume change, log trade count,
hour sin/cos và weekday sin/cos (Monday=0). `close_position=0.5` khi high=low;
không chia cho epsilon tùy ý. Wick dùng `max(O,C)` / `min(O,C)` đúng công thức proposal.

XGBoost lấy cả 13 feature tại `t`, cộng lag khác 0 của sáu series trong proposal;
momentum `6/12/24/72/168`, std return `6/24/72/168` (`ddof=0`),
quote-volume z-score `24/168` (bằng 0 khi std=0). Cửa sổ rolling gồm row hiện tại.
Feature names/thứ tự được lưu cùng artifact; chỉ cột đã liệt kê được đưa vào model.
Không dùng raw timestamp, target, giá tương lai, batch ID hoặc loaded_at làm feature.

## 4. Dataset → train/evaluation

Split theo **`target_open_time`**; không random split:

| Partition | Target open time |
| --- | --- |
| Train | Từ lịch sử khả dụng năm 2020 đến trước 2025-01-01 |
| Validation | Từ 2025-01-01 đến trước 2026-01-01 |
| Final test | Từ 2026-01-01 đến ngày kết thúc snapshot đã đóng băng |

Context được phép đi qua ranh partition về quá khứ. Mọi label train phải đóng
không muộn hơn cutoff của sample validation đầu tiên; kiểm tra tương tự khi
đánh giá walk-forward. Không fit preprocessing trên validation/test.
Dataset thiếu partition phải fail rõ ràng, không tự đổi split.

Lần đầu dùng một cấu hình cố định, không hyperparameter search:

```text
objective=reg:squarederror, eval_metric=mae, tree_method=hist
n_estimators=500, learning_rate=0.03, max_depth=3
min_child_weight=20, subsample=0.8, colsample_bytree=0.8
reg_alpha=0, reg_lambda=10, random_state=42, n_jobs=2
early_stopping_rounds=30, eval_set=validation only
```

XGBoost không cần scaler ở lần đầu. Early stopping dùng validation MAE, tuyệt đối
không dùng final test. Lưu best iteration và dùng đúng iteration đó khi predict.
Các tham số thuộc `settings.yaml` khi triển khai; đường dẫn/DB thuộc `.env`.

Metric trên cùng sample cho cả ba phương pháp:

- Chính: MAE log-return; Relative MAE = model MAE / zero-return MAE.
- Phụ: RMSE return, MAE giá USDT, directional accuracy với `sign(0)=0`.
- Báo cáo toàn validation và từng tháng, kèm số sample và tỷ lệ bị loại.
- Baseline MAE bằng 0: Relative MAE là null, không chia 0; candidate không đạt gate.

Gate nghiên cứu ban đầu: MAE toàn validation thấp hơn **cả hai** baseline và
thắng zero-return ở ít nhất 7/12 tháng validation; mỗi tháng phải có tối thiểu
500 sample hợp lệ. Thiếu coverage → `insufficient_data`; không thắng → `rejected`.
Đây là tiêu chí do project chọn, không phải bằng chứng về lợi nhuận giao dịch.

Sau khi khóa feature/config và candidate, chạy final test để báo cáo; test score
không được dùng để chọn model/retrain. Nếu sửa thiết kế sau khi xem test, đánh dấu
test đã bị sử dụng và dành kỳ tương lai mới làm holdout. Chưa tự động promote live
chỉ vì vượt gate validation: còn phải kiểm chứng freshness, recovery và artifact.

## 5. Run/artifact và lineage

Mỗi lần train có UUID `run_id` mới, không ghi đè artifact run cũ. Lưu cả run bị
từ chối. `model_version=run_id`; feature schema có tên cố định `hourly-return-v1`.

Run bundle phải có:

- `model.ubj`, SHA-256; native XGBoost format, không chỉ pickle.
- Snapshot dữ liệu và SHA-256, query/code version, git commit và trạng thái dirty.
- Feature names/order, config, seed, package versions, best iteration.
- Split boundaries, snapshot end, sample counts và số sample bị loại theo lý do/split.
- Metrics hai baseline/model, decision và thời gian train.
- Toàn bộ source batch IDs của snapshot; mỗi forecast truy được đủ batch của
  169 nến input, không chỉ batch của nến cuối cùng.

Snapshot là **lịch sử warehouse tại lúc extract**, có thể chứa chỉnh sửa sau này;
chưa chứng minh đây là dữ liệu được biết tại từng thời điểm quá khứ. Ghi rõ hạn chế
point-in-time này trong báo cáo backtest. Retain snapshot để không train lại trên
dữ liệu đã thay đổi mà vẫn gọi là cùng dataset.

## 6. Forecast → API/UI/agent (contract để triển khai)

Endpoint riêng: `GET /v1/assets/{symbol}/hourly-forecast`. Giữ envelope hiện có:
`{status, data, provenance, quality, trace_id}`. Không đổi endpoint daily `/prediction`.

`data` khi ready gồm:

```text
symbol, pair, quote_currency="USDT", horizon_hours=1
input_open_time, cutoff_time, generated_at, target_open_time, target_close_time
reference_close_usdt, predicted_log_return, forecast_close_usdt
model_name="xgboost", model_version, feature_version="hourly-return-v1"
```

Mọi timestamp là RFC3339 UTC; số phải hữu hạn, reference/forecast close > 0.
`provenance` mang snapshot ID/checksum và lineage reference tới model/run/input.
Ground truth chỉ ghi sau target close; không nằm trong response forecast hiện tại.

| Status | Nghĩa / hành vi |
| --- | --- |
| `ready` | Model đã promote, input đủ/mới và forecast chưa hết hạn |
| `stale` | Input quá SLA hoặc forecast hết hạn; `data=null` |
| `insufficient_data` | Thiếu nến, feature hoặc model chưa vượt gate; `data=null` |
| `unavailable` | Chưa có model được promote hoặc dependency lỗi; `data=null` |

`quality.warnings` chứa reason code phân biệt `input_gap`, `input_stale`,
`forecast_expired`, `model_rejected`, `no_promoted_model`, `dependency_error`.
Coin ngoài BTC/ETH/SOL trả HTTP 422. BTC được triển khai trước; coin chưa có
model trả `unavailable`, không trả forecast của BTC thay thế.
UI ghi “Dự báo giá đóng lúc … UTC”, tách khỏi giá thực tế; agent chỉ đọc output.

## 7. Runtime và phạm vi bước đầu

```text
Batch ZIP → hourly warehouse → frozen dataset → baseline + BTC XGBoost
                                              → evaluation + run artifacts

Hourly closed-candle ingestion [CHƯA CÓ] → validated input → promoted model
                                                       → hourly forecast API [CHƯA CÓ]
```

ZIP daily/monthly phục vụ lịch sử train. Inference sau này lấy nến `1h` đã đóng
qua Binance REST, qua cùng validation rồi upsert warehouse; dùng ZIP để đối soát.
Cần lưu transport/revision lineage và kiểm chứng train/serve parity trước khi bật.
Không dùng aggregate Spark 7 ngày hay đủ 60 phút nhưng chưa kiểm continuity để
giả làm nến giờ. Airflow train có thể chạy hằng tuần; inference phải được kích hoạt
sau input hợp lệ, không chỉ đặt lịch rồi giả định ingestion đã xong.

Hiện kiểm tra DB ngày 09/10/2026: BTC/ETH/SOL mỗi coin 6.672 nến giờ,
01/01/2026–05/10/2026. **Thiếu train/validation 2020–2025**. Bước tiếp theo là
backfill BTC lịch sử, freeze snapshot, viết dataset/tests rồi train cấu hình trên.
Không dùng test 2026 làm train để bỏ qua thiếu dữ liệu.

Nghiệm thu implementation đầu tiên: gap/boundary/future-perturbation tests đạt;
train thật BTC xuất artifact và báo cáo baseline, kể cả bị rejected; test cuối chưa
bị dùng để tune. Schema registry, API, hourly ingest và UI forecast là bước tiếp sau.

Tham chiếu API thư viện: [XGBoost Python API](https://xgboost.readthedocs.io/en/stable/python/python_api.html).
