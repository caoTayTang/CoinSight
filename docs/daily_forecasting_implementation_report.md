# Daily close forecasting — implementation report và cách train

Phần serving support và cách daily quantile forecast được chuyển thành quyết
định Paper Trade nằm tại
[Daily quantile trading policy](trading_policy_guide.md).

## 1. Kết quả triển khai

Pipeline forecasting hiện hỗ trợ hai frequency mà không xóa workflow hourly cũ:

- `1h`: snapshot/run hourly cũ vẫn đọc được.
- `1d`: dự đoán giá đóng cửa của nến UTC ngày kế tiếp.

Cấu hình mặc định trong `pipeline/settings.yaml` đã chuyển sang:

```yaml
forecasting:
  frequency: 1d
  feature_version: daily-return-v2
  context_symbols: [BTC, ETH, SOL]
  lookback_periods: 90
  horizon_periods: 1
  rolling_baseline_periods: 30
  minimum_month_samples: 20
```

Một sample daily có nghĩa là:

```text
Input:  90 nến ngày đã đóng, kết thúc ở ngày d
Target: log(close[d+1] / close[d])
Output: predicted_close[d+1] = close[d] * exp(predicted_log_return)
```

`target_time` là thời điểm mở của nến ngày cần dự báo. Dự báo được tạo sau
khi nến input cuối cùng đã đóng; với horizon một ngày thì
`cutoff_time == target_time`.

## 2. Luồng dữ liệu

```text
Binance archive 1d
    ↓
staging.stg_ohlcv
    ↓ DQ + warehouse loader
dw.fact_ohlcv_daily
    ↓ DailyCandleRepository
DailyFeatureExtractor cho target và context coins
    ↓ align chính xác theo UTC date + feature fusion
    ↓
SampleIndexBuilder (frequency=1d)
    ↓ chronological train/validation/test split
immutable snapshot
    ├── candles.parquet
    ├── features.parquet
    ├── samples.parquet
    └── manifest.json
    ↓
XGBoost / GRU / LSTM
    ↓
validation + baseline comparison + artifacts
    ↓ seal candidate
final test backtest
```

Pipeline đọc trực tiếp grain `dw.fact_ohlcv_daily`, không resample nến giờ.

## 3. Feature daily-return-v1 và daily-return-v2

Feature hiện tại của một nến:

```text
log_return_1d, open_close_return, high_low_range,
close_position, upper_wick, lower_wick,
log_volume, volume_change, log_trade_count,
dow_sin, dow_cos
```

Feature rolling:

```text
momentum:         7, 14, 30, 60, 90 ngày
volatility:       7, 14, 30, 60, 90 ngày
volume z-score:   7, 30, 90 ngày
volatility ratio: volatility_7d / volatility_30d
```

Tổng cộng một timestep có 25 feature. Rolling dài nhất là 90 ngày nên các
dòng warm-up đầu tiên có `feature_valid=false` và không được train.

`daily-return-v1` giữ layout target-only để tái lập các run cũ:

```text
GRU/LSTM: [sample_count, 90, 25]
XGBoost:  [sample_count, 86]
```

XGBoost nhận feature tại cutoff, lag 1/2/3/7/14/30/60/89 ngày và các rolling
summary. GRU/LSTM nhận nguyên sequence 90 × 25. Scaler chỉ fit trên train.

`daily-return-v2` tính cùng 25 feature cho target và từng coin trong
`context_symbols`, căn theo UTC date rồi nối theo chiều feature. Ví dụ target BTC
với context `[BTC, ETH, SOL]` tạo input recurrent `[sample_count, 90, 75]`.
Tên cột có dạng `BTC__log_return_1d`, `ETH__momentum_30d`; thứ tự luôn là
target trước, sau đó context theo alphabet. Dữ liệu tại ngày `t+1` không được dùng.

V2 hiện dành cho GRU/LSTM và các sequence model. XGBoost bị từ chối rõ ràng thay
vì âm thầm bỏ qua context; muốn benchmark XGBoost target-only phải tạo snapshot
`daily-return-v1`.

## 4. Baseline và đánh giá

Mọi model được so trên cùng sample với:

1. Zero-return: `predicted_return = 0`, tức close ngày mai bằng close hôm nay.
2. Rolling mean: return trung bình 30 ngày gần nhất.

Metric gồm MAE/RMSE return, MAE/sMAPE price, relative MAE, directional
accuracy, Pearson và Spearman. Daily chỉ có khoảng 28–31 sample/tháng nên
`minimum_month_samples=20`, thay cho 500 của hourly.

## 5. File đã thay đổi

| File | Mục đích |
| --- | --- |
| `pipeline/settings.yaml` | Chọn daily, lookback 90 và baseline 30 ngày. |
| `pipeline/settings.py` | Validate frequency, period và feature version. |
| `pipeline/decision/config.py` | Period-neutral config và `last_closed_period()`. |
| `pipeline/decision/data/warehouse_repository.py` | Đọc `dw.fact_ohlcv_daily`. |
| `pipeline/decision/data/coverage.py` | Audit được khoảng cách giờ/ngày. |
| `pipeline/decision/data/feature_extractor.py` | 25 daily feature leakage-safe và fusion cross-asset V2. |
| `pipeline/decision/data/sample_index.py` | Target, continuity và cutoff theo frequency. |
| `pipeline/decision/data/snapshot.py` | Manifest period-neutral. |
| `pipeline/decision/data/input_adapters.py` | Input XGBoost daily. |
| `pipeline/decision/data/dataloader.py` | Sequence daily và baseline `log_return_1d`. |
| `pipeline/decision/data/split.py` | Expanding fold theo ngày. |
| `pipeline/decision/evaluation/evaluator.py` | Rolling evaluation theo period. |
| `pipeline/decision/training/run_training.py` | Policy từ snapshot, lưu frequency. |
| `pipeline/decision/inference/predictor.py` | Input daily và target ngày kế tiếp. |
| `pipeline/decision/cli.py` | Chọn repository/cutoff theo frequency. |
| `tests/decision/forecasting/test_daily_pipeline.py` | Test daily end-to-end ở mức component. |

Các field `*_hours` bên trong `ForecastDataConfig` được giữ làm compatibility
alias cho test/snapshot hourly cũ. YAML và manifest mới dùng `*_periods`.

## 6. Chuẩn bị dữ liệu

### 6.1 Khởi động database

```bash
docker compose up -d postgres migrate
docker compose ps postgres
```

### 6.2 Cài dependency

Lần đầu:

```bash
make setup
```

Nếu `.venv` đã tồn tại và không muốn tạo lại:

```bash
uv pip install --python .venv/bin/python \
  -r pipeline/requirements.txt -r app/requirements.txt
```

### 6.3 Tải riêng daily data của BTC

```bash
DATABASE_URL=postgresql://crypto:crypto@localhost:5432/crypto_dw \
RAW_DIR=data/raw \
.venv/bin/python -m pipeline.batch.ingest_binance_history \
  --symbols BTC \
  --intervals 1d \
  --start 2017-08
```

Binance không có BTC Spot archive từ đầu 2016; downloader sẽ ghi nhận period
không tồn tại. Không tự sinh nến để lấp phần lịch sử đó.

Muốn tải theo toàn bộ `batch.symbols`, interval và `start_month` trong settings:

```bash
make extract
```

### 6.4 Nạp staging vào Data Warehouse

```bash
make batch
```

Kiểm tra coverage:

```bash
docker compose exec -T postgres psql -U crypto -d crypto_dw -c "
select a.symbol, min(d.full_date) first_day, max(d.full_date) last_day,
       count(*) daily_candles
from dw.fact_ohlcv_daily f
join dw.dim_asset a using (asset_key)
join dw.dim_date d using (date_key)
where a.symbol = 'BTC'
group by a.symbol;
"
```

## 7. Tạo snapshot

Kiểm tra settings trước:

```yaml
forecasting:
  symbols: [BTC]
  context_symbols: [BTC, ETH, SOL]
  frequency: 1d
  feature_version: daily-return-v2
  lookback_periods: 90
  horizon_periods: 1
  rolling_baseline_periods: 30
  minimum_month_samples: 20
```

`validation_start` và `test_start` phải nằm trong coverage. Nên dành ít nhất
12 tháng validation để monthly acceptance rule có ý nghĩa.

Cutoff là exclusive. Nếu `last_day=2026-10-18`, dùng:

```bash
make forecast-dataset \
  SYMBOL=BTC \
  CUTOFF=2026-10-19T00:00:00Z
```

Hoặc dùng đầu ngày UTC hiện tại:

```bash
make forecast-dataset SYMBOL=BTC
```

Ghi lại `snapshot_id` từ JSON output và kiểm tra:

- `frequency` phải là `1d`;
- `feature_version` phải là `daily-return-v2` cho recurrent multi-coin;
- `asset_order` và `sequence_feature_names` phải đúng universe đã cấu hình;
- `row_counts.context_candles` phải lớn hơn 0 nếu có context coin;
- `row_counts.valid_samples` phải lớn hơn 0;
- xem `rejections` có `missing_day` bất thường hay không.

Snapshot nằm tại:

```text
data/forecasting/snapshots/<snapshot_id>/BTC/
```

## 8. Train XGBoost target-only

XGBoost hiện chỉ dùng snapshot `daily-return-v1`. Hãy đổi feature version, build
snapshot riêng rồi chạy:

```bash
make forecast-train \
  SYMBOL=BTC \
  MODEL=xgboost \
  SNAPSHOT_ID=<snapshot_id> \
  SEED=42
```

Run nằm tại:

```text
data/forecasting/runs/BTC/xgboost/<run_id>/
```

Đọc validation result:

```bash
python -m json.tool \
  data/forecasting/runs/BTC/xgboost/<run_id>/validation_metrics.json
```

Các artifact chính: `model.ubj`, `model_config.json`, `feature_names.json`,
`validation_metrics.json`, `validation_monthly.csv`,
`validation_predictions.parquet` và `manifest.json`.

Promotion hiện ưu tiên mục tiêu support giao dịch:

- majority UP/DOWN được chọn duy nhất từ tập train;
- model phải thắng accuracy của majority baseline trên validation;
- balanced accuracy phải lớn hơn `0.5`;
- model phải thắng majority baseline ở quá nửa số tháng validation đủ sample.

MAE so với zero-return/rolling-mean, `relative_mae`, correlation,
`movement_scale_ratio`, `copy_rate` và `beat_persistence_rate` vẫn được lưu làm
diagnostic. Chúng không còn tự động reject candidate vì magnitude forecast chưa
thắng persistence.

## 9. Train GRU và LSTM

Run recurrent mới dùng quantile forecasting và persistence-ranking loss:

```text
total_loss = mean(pinball_loss(q10), pinball_loss(q50), pinball_loss(q90))
           + persistence_loss_weight × persistence_ranking
```

GRU/LSTM dùng một head trung tâm và một head khoảng trên cùng hidden state:

```text
q50 head:       median return và persistence-ranking
interval head:  khoảng cách dương để tạo q10 và q90
```

Predicted price vẫn chỉ được dựng từ q50. `PredictionResult` trả thêm
`return_q10`, `return_q50`, `return_q90` và `forecast_confidence`. Quy tắc
confidence là `q10 > 0` → `confident_up`, `q90 < 0` → `confident_down`, khoảng
cắt qua zero → `uncertain`. Đây không phải xác suất đã hiệu chỉnh. Run cũ có
direction head vẫn load và infer theo contract cũ.

Config mặc định:

```text
persistence_loss_weight      = 1.1
persistence_margin_fraction  = 0.25
minimum_actual_move          = 0.001
```

Loss so sánh predicted return với zero-return của cùng sample. Không dùng
`shift()` hoặc `torch.roll()` vì training DataLoader có shuffle. Validation
bị đánh dấu `prediction_collapse_toward_persistence` khi
`movement_scale_ratio < 0.25`.

Cả hai dùng lại cùng snapshot:

```bash
make forecast-train SYMBOL=BTC MODEL=gru \
  SNAPSHOT_ID=<snapshot_id> SEED=42
```

```bash
make forecast-train SYMBOL=BTC MODEL=lstm \
  SNAPSHOT_ID=<snapshot_id> SEED=42
```

Không sửa `RecurrentConfig.input_size` bằng tay. Orchestrator đọc snapshot và
tự đặt input size bằng 25. `lookback_periods=90` là sequence length.

Checkpoint nằm trong run:

```text
best_checkpoint.pt
last_checkpoint.pt
model.pt
scaler.json
target_scaler.json
```

Resume GRU/LSTM bị dừng:

```bash
make forecast-resume RUN_ID=<run_id>
```

Resume yêu cầu run ở trạng thái `running`/`failed`, config và snapshot không
đổi, đồng thời `last_checkpoint.pt` còn tồn tại.

## 10. Final test backtest

Chỉ seal sau khi đã quyết định model/config bằng validation:

```bash
make forecast-seal RUN_ID=<run_id>
make forecast-backtest RUN_ID=<run_id>
```

Kết quả gồm `test_metrics.json`, `test_monthly.csv`,
`test_predictions.parquet` và marker `TEST_CONSUMED`. Không chỉnh
hyperparameter theo kết quả test; nếu cần thử lại, tạo run mới và quyết định
chỉ trên validation.

### Chạy tự động toàn bộ workflow và tạo biểu đồ

Entry point `pipeline/decision/train.py` nhận snapshot ID rồi tự động chạy:

```text
train → validation → seal → test → confusion matrix → price plot → report
```

Ví dụ GRU trên GPU:

```bash
make forecast-auto \
  SNAPSHOT_ID=<snapshot_id> \
  MODEL=gru \
  SEED=42 \
  DEVICE=cuda
```

Hoặc gọi module trực tiếp:

```bash
.venv/bin/python -m pipeline.decision.train <snapshot_id> \
  --model gru \
  --seed 42 \
  --device cuda
```

Nếu snapshot ID chứa nhiều symbol, truyền thêm `--symbol BTC` hoặc
`SYMBOL=BTC`. Nếu chỉ có một symbol, chương trình tự phát hiện.

Các artifact bổ sung trong thư mục run:

```text
test_evaluation_report.md
test_direction_metrics.json
test_confusion_matrix.png
test_quantile_metrics.json
test_price_forecast.png
```

Ma trận nhầm lẫn dùng quy tắc return `> 0` là UP, return `<= 0` là DOWN và
báo riêng số đúng/sai khi model dự đoán UP hoặc DOWN.
`test_quantile_metrics.json` báo empirical coverage của khoảng q10-q90, độ
rộng trung bình, số tín hiệu confident UP/DOWN/uncertain và directional
accuracy chỉ trên các sample confident. Artifact `direction_head` chỉ xuất
hiện khi backtest một checkpoint two-head cũ.

Lưu ý: chế độ tự động sẽ consume test kể cả khi candidate bị validation
reject, vì đây là workflow được yêu cầu. Không nên dùng lệnh này trong vòng
lặp tune hyperparameter; khi nghiên cứu nghiêm ngặt, dùng `forecast-train`
trước và chỉ seal/backtest candidate đã chốt.

## 11. Chạy nhiều seed

```bash
for seed in 42 123 2026; do
  make forecast-train SYMBOL=BTC MODEL=xgboost \
    SNAPSHOT_ID=<snapshot_id> SEED=$seed
done
```

So sánh mean và độ lệch giữa seed; không chọn seed tốt nhất bằng final test.

## 12. Kiểm thử

```bash
.venv/bin/python -m pytest \
  tests/decision/forecasting/test_daily_pipeline.py -q
```

```bash
.venv/bin/python -m pytest tests/decision/forecasting -q
```

Smoke test đã xác nhận:

```text
XGBoost daily input: (sample_count, 86)
GRU daily input:     (sample_count, 90, 25)
daily target:        finite
daily inference:     target_time = latest input day + 1 day
daily V2 recurrent:  [sample_count, 90, 25 × asset_count]
```

## 13. Giới hạn hiện tại

- `daily-return-v2` chưa hỗ trợ XGBoost multi-coin; dùng V1 cho baseline XGBoost.
- Mọi context coin phải có daily candle cùng timestamp. Coin ra đời muộn sẽ làm
  thời điểm bắt đầu hữu dụng dịch tới sau ngày ra đời khoảng 180 daily candles:
  90 ngày feature warm-up cộng cửa sổ input 90 ngày.
- Transformer vẫn thuộc phase sau.
- `ForecastPredictor` build input daily được, nhưng `ForecastRepository` và
  `dw.fact_hourly_forecast` vẫn là contract hourly. Không ghi daily prediction
  vào bảng hourly; cần migration bảng daily/generic trước khi publish vào API
  hoặc LLM tool.
- Command `pipeline.decision.cli backfill` vẫn dành cho raw archive `1h`.
  Lịch sử daily dùng `ingest_binance_history --intervals 1d` như trên.
