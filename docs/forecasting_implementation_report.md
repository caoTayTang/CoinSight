# Báo cáo triển khai pipeline dự báo theo giờ

> Ngày: 13/10/2026
> Thiết kế gốc: [forecasting_design.md](forecasting_design.md)
> Kế hoạch: [forecasting_implementation_plan.md](forecasting_implementation_plan.md)

## 1. Kết quả

Đã triển khai pipeline offline cho bài toán dự báo next-hour log-return trong
`pipeline/decision/`. Pipeline hỗ trợ XGBoost, GRU và LSTM từ khâu đọc warehouse
đến snapshot, train, validation, artifact và fixed-model backtest. Data loader
đã có contract cho PatchTST/iTransformer nhưng class model Transformer chưa được
triển khai, đúng phạm vi phase sau.

Không tái sử dụng pipeline direction classifier dummy làm kiến trúc chính. Schema
hourly regression và artifact của nó độc lập với Brier score/probability contract cũ.

## 2. Thành phần đã triển khai

### Dữ liệu và backfill

- `HourlyCandleRepository`: đọc một coin, nguồn Binance, khoảng thời gian nửa mở.
- `CoverageAuditor`: kiểm duplicate và gom các giờ thiếu thành missing ranges.
- `BackfillService`: audit DW trước, gom exact missing ranges, ánh xạ sang bộ
  monthly/daily Binance archive tối thiểu, kiểm raw cache và
  `meta.loaded_archive`, stage với `replace=False`, UPSERT rồi audit lại.
- Monthly archive của tháng trước có thể fallback sang đúng các ngày bị thiếu;
  gap thuộc ngày UTC chưa hoàn tất được báo bằng `deferred_hours` thay vì gọi
  archive chắc chắn chưa được phát hành.
- Kết quả backfill phân biệt archive mới, archive đã đổi checksum và archive
  checksum không đổi nhưng cần stage lại để sửa gap trong DW.
- `SnapshotBuilder`: xuất `candles.parquet`, `features.parquet`, `samples.parquet`
  và manifest có SHA-256, batch IDs, data cutoff, split và rejection counts.
- Snapshot ID phụ thuộc dữ liệu, feature version, lookback, horizon và boundaries.

### Feature và sample

- `hourly-return-v1` vẫn được hỗ trợ để load/resume run cũ với 13 feature chung.
- `hourly-return-v2` tính 27 feature giống nhau cho từng asset: 13 base feature,
  momentum và realized volatility `6/24/72/168/336h`, volume z-score
  `24/168/336h` và volatility ratio `24h/168h`.
- Target và context được align chính xác theo timestamp rồi concatenate theo chiều
  feature; target đứng trước, các context coin theo alphabet. Không còn market aggregate.
- Với universe mặc định 20 coin, recurrent input là `[B,336,540]`. Asset/feature
  order được lưu trong manifest và scaler để train/inference không lệch cột.
- V2 cho phép universe chỉ có target; ví dụ `context_symbols: [BTC]` tạo input
  `[B,336,27]`, snapshot và inference không tải context candles.
- V2 yêu cầu đủ dữ liệu của mọi asset tại timestamp tương ứng; thiếu coin/gap làm
  sample invalid. Context data và batch IDs tham gia snapshot identity/manifest.
- Return/change sau continuity gap được đánh invalid, không tính như return nhiều giờ.
- V1 cần 170 nến liên tiếp cho sample lookback 168. V2 cần tối đa 673 nến
  `t-671 ... t+1`: 336 giờ warm-up, 336 feature rows và một nhãn tương lai.
- Mỗi sample có stable ID, cutoff/target, row offsets, giá tham chiếu, target và
  rejection reason.
- Split theo `target_time`: train trước 2025, validation năm 2025, test từ 2026
  đến snapshot cutoff.
- `SequenceScaler` chỉ fit trên các feature row duy nhất được dùng bởi train và
  lưu mean/std dưới dạng JSON.

### Model-aware loader

`ForecastDataModule` nhận `ModelType` và tạo input:

| Model | Shape |
| --- | --- |
| XGBoost | `[N,78]`, target `[N]` |
| GRU | v1: `[B,L,13]`; v2 mặc định: `[B,336,540]`, target `[B,1]` |
| LSTM | v1: `[B,L,13]`; v2 mặc định: `[B,336,540]`, target `[B,1]` |
| PatchTST | `[B,13,168]`, target `[B,1]` |
| iTransformer | `[B,168,13]`, target `[B,1]` |

XGBoost giữ adapter 78 chiều hiện tại để thí nghiệm v2 tập trung vào recurrent.
Sequence model lấy feature order từ snapshot/scaler; recurrent `input_size` được
suy ra tự động thay vì hard-code. Train window có thể
shuffle nhưng thứ tự bên trong window không đổi; validation/test giữ thứ tự thời gian.
Timeline sequence được chuyển sang NumPy và scale đúng một lần trong `setup()`;
`__getitem__` chỉ lấy slice theo row offset, không cắt/scale pandas lại cho từng sample.
`TrainingConfig.num_workers` mặc định là 2, worker được giữ sống giữa các epoch;
CUDA dùng pinned memory và non-blocking host-to-device copy. Rolling-mean baseline
chỉ đọc 24 target-return cần thiết thay vì materialize toàn bộ tensor v2.

### Model và training

- `XGBoostForecastModel`: `XGBRegressor`, early stopping bằng validation, native
  UBJ save/load và kiểm tra feature order.
- `GRURegressor` và `LSTMRegressor`: recurrent encoder một chiều, final hidden
  state, dropout và linear regression head.
- `TorchTrainer`: Huber loss, AdamW, gradient clipping, validation MAE, early
  stopping và restore checkpoint tốt nhất.
- Training CLI in đầy đủ model/training/data config trước khi chạy. GRU/LSTM
  hiển thị epoch, batch hiện tại/tổng batch, running Huber loss hoặc validation
  MAE, best MAE, patience và thời gian mỗi epoch; prediction validation cũng có
  tiến độ theo batch. Tần suất được điều khiển bằng
  `TrainingConfig.progress_every_batches` và có thể tắt qua `show_progress`.
- XGBoost hiển thị validation MAE mỗi `verbose_eval` boosting rounds, sau đó báo
  best round, best validation MAE và tổng số rounds đã chạy.
- `TrainingOrchestrator`: không đọc TEST; luôn lưu run accepted/rejected/failed,
  model config, training config, package versions, history, validation predictions
  và checksums.
- XGBoost được nâng từ `2.1.1` lên `2.1.4` vì smoke test phát hiện `2.1.1` không
  tương thích với `scikit-learn 1.6.1` khi load native artifact.

### Evaluation và backtest

- Hai baseline bắt buộc: zero-return và rolling-mean return 24 giờ.
- Metrics: MAE/RMSE return, MAE/sMAPE price USDT, relative MAE, directional
  accuracy, Pearson và Spearman.
- Model và baseline luôn dùng cùng sample IDs.
- Có báo cáo theo tháng và candidate rule trên validation.
- Final TEST cần validation run được seal; cùng run ID chỉ claim TEST một lần.
- Fixed-model backtest chạy theo target time tăng dần.
- Walk-forward interface kiểm tra các fold không overlap; chưa chạy training thật.

### Artifact, registry và inference

- Run artifact có UUID, manifest và SHA-256; XGBoost lưu `.ubj`, recurrent model
  lưu `state_dict`, sequence scaler lưu JSON.
- Migration `010_hourly_forecasting.sql` tạo training run, evaluation, promoted
  model, hourly forecast và input lineage tables.
- Promotion là transaction và chỉ cho run có status `tested`; mỗi coin/horizon
  chỉ có một model active.
- `InferenceInputBuilder` v1 yêu cầu `lookback + 1` nến đóng. V2 yêu cầu
  `lookback + 168` nến target để warm-up rolling feature và context candles của
  cùng universe; thiếu context thì fail thay vì âm thầm thay bằng zero.
- `ForecastRepository` chỉ ghi prediction khi run là active promoted model và
  bắt buộc có ETL batch lineage.

### CLI và Make targets

Đã thêm các subcommand:

```text
audit-data
backfill
build-dataset
train
seal
backtest
```

Và Make targets tương ứng:

```text
forecast-audit
forecast-backfill
forecast-dataset
forecast-train
forecast-seal
forecast-backtest
```

## 3. Database changes

Hai file cùng contract được thêm:

- `postgres/init/06_hourly_forecasting.sql`: database mới.
- `postgres/migrations/010_hourly_forecasting.sql`: database đã tồn tại.

Không thay đổi semantics của bảng/model direction cũ.

## 4. Kiểm thử

Forecasting suite:

```text
48 passed
```

Bao gồm:

- Công thức feature, flat candle và future-mutation leakage test.
- Continuity gap và sample 170 nến.
- Boundary split chính xác.
- Train-only scaler.
- Shape và sample parity của cả năm model type.
- Baseline và metrics tính tay.
- XGBoost fit/save/load parity.
- GRU/LSTM forward, backward và training smoke test.
- Snapshot immutability/checksum.
- Artifact checksum và one-time TEST claim.
- XGBoost orchestrator end-to-end trên Parquet snapshot synthetic.
- GRU orchestrator end-to-end, checkpoint `state_dict` và scaler artifact.
- Input parity cho inference.

Full repository suite:

```text
74 passed, 8 skipped, 1 warning
```

Tám test bị skip là integration tests cần PostgreSQL đang chạy. Warning còn lại
đến từ alias deprecated bên trong Starlette TestClient, không thuộc forecasting.
Ruff check trên toàn bộ file forecasting mới: pass.

## 5. Chưa thực hiện trên dữ liệu thật

Tại thời điểm kiểm tra, `docker compose ps` không có service đang chạy. Vì vậy
chưa thực hiện các hành động làm thay đổi dữ liệu sau:

- Chưa chạy migration trên PostgreSQL thật.
- Chưa audit/backfill BTC từ Binance.
- Chưa tạo snapshot từ `dw.fact_ohlcv_hourly` thật.
- Chưa train/backtest XGBoost, GRU hoặc LSTM trên lịch sử thật.
- Chưa promote model hay ghi forecast thật.

Đây là giới hạn môi trường chạy, không được thay bằng kết quả synthetic trong
báo cáo chất lượng model.

## 6. Phần cố ý để phase sau

- Model class và trainer cho PatchTST-based/iTransformer-based.
- Hyperparameter search.
- Airflow DAG retrain/inference theo giờ.
- FastAPI/dashboard route cho hourly forecast.
- Trading strategy backtest, fee, slippage và PnL.

## 7. Lệnh chạy tiếp theo

Sau khi bật PostgreSQL và migration:

```bash
make up
# Kiểm tra dữ liệu của một SYMBOL đang có gì trong DW, cho biết được là có missing range k
make forecast-audit SYMBOLS=BTC
# Nếu có thì backfill, sẽ chỉ tải lại các range còn thiếu, truyền tới month thôi(nếu binance có, k có thì nhót)
make forecast-backfill SYMBOLS=BTC START=2020-01
# Kiểm tra lại
make forecast-audit SYMBOLS=BTC
# Tạo dataset để train model, hiện tại train model cho SYMBOL nào thì truyền SYMBOL đó vô
make forecast-dataset SYMBOL=BTC CUTOFF=2026-10-13T00:00:00Z
# Chạy lệnh trên xong trong report ở terminal sẽ có snapshot ID mới tạo ra, truyền nó vô
make forecast-train SYMBOL=BTC MODEL=xgboost SNAPSHOT_ID=... SEED=42
```

Kết quả sau khi train xong sẽ nằm trong data/forecasting/runs/BTC/<modelType>/<run_id>

Với GRU/LSTM, mỗi run ghi checkpoint trực tiếp trong thư mục theo `run_id`:

- `last_checkpoint.pt`: trạng thái epoch hoàn tất gần nhất, gồm model, optimizer,
  early stopping, training history và RNG state; dùng để resume.
- `best_checkpoint.pt`: weights có validation MAE tốt nhất ngay tại thời điểm train.
- `model.pt`: best weights đã được restore sau khi train xong; đây là artifact dùng
  cho inference và backtest.
- `target_scaler.json`: mean/std của `target_log_return` chỉ fit trên training split.
  GRU/LSTM học target đã standardize; validation, test và inference luôn inverse
  transform về log-return gốc trước khi tính metric hoặc giá dự báo.

Loss hiện tại:

- XGBoost tối ưu `reg:squarederror`; validation MAE dùng cho early stopping.
- GRU/LSTM tối ưu Huber trên standardized return. Có thể thêm auxiliary direction
  BCE bằng `TrainingConfig.direction_loss_weight`. Công thức là
  `Huber + weight * BCE`; mặc định `weight=0.0` để giữ nguyên regression baseline.
  Giá trị khởi đầu nên thử là `0.05` hoặc `0.1`, và chỉ chọn bằng validation.

Nếu process bị dừng sau ít nhất một epoch hoàn tất, tiếp tục đúng run cũ bằng:

```bash
make forecast-resume RUN_ID=<run_id>
```

Resume chỉ áp dụng cho GRU/LSTM có trạng thái `running` hoặc `failed`. Run đã
`accepted`, `rejected` hay `tested` không được sửa để bảo toàn manifest và kết quả
đánh giá. XGBoost hiện vẫn dùng early stopping nội bộ và chưa hỗ trợ resume.

Model sẽ có giá trị khi Mae của nó nhỏ hơn zero-return MAE và rolling-mean MAE

Chỉ seal và mở TEST sau khi validation report/config đã được duyệt:

```bash
make forecast-seal RUN_ID=...
make forecast-backtest RUN_ID=...
```

Sau XGBoost BTC, chạy GRU/LSTM với ba seed rồi mới mở rộng ETH/SOL và hai
Transformer-based model.
