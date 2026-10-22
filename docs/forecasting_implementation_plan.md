# Kế hoạch triển khai pipeline dự báo giá theo giờ

> Trạng thái: kế hoạch triển khai, chưa phải code đã hoàn thành.
> Nguồn thiết kế: [forecasting_design.md](forecasting_design.md).
> Phạm vi giai đoạn đầu: XGBoost, GRU và LSTM; data pipeline chuẩn bị sẵn
> contract cho PatchTST-based và iTransformer-based.
> Nơi triển khai chính: `pipeline/decision/`.

## 1. Kết quả cần đạt

Pipeline phải tạo được cùng một bài toán cho mọi model:

```text
169 nến đầu vào thô liên tiếp t-168 ... t
        ↓
13 feature/candle × 168 giờ
        ↓
target = log(close[t+1] / close[t])
        ↓
┌───────────┬──────────────┬──────────────┐
│ XGBoost   │ GRU / LSTM   │ Transformer  │
│ [N, F]    │ [N,168,13]   │ adapter riêng│
└───────────┴──────────────┴──────────────┘
        ↓
predicted_log_return và predicted_close_usdt
```

Các quyết định V1:

- Dữ liệu: `dw.fact_ohlcv_hourly`, nguồn `binance`.
- Coin: BTC, ETH, SOL; hoàn thiện toàn bộ flow với BTC trước.
- Một model instance riêng cho mỗi coin.
- Lookback: 168 feature rows. Cần 169 nến thô để tính feature ở row đầu;
  training cần thêm candle `t+1` để tạo label, tức 170 nến liên tiếp.
- Horizon: một giờ; label cần thêm candle `t+1`.
- Target: next-hour log-return.
- Split theo `target_time`, tuyệt đối không random split.
- Dataset snapshot lưu Parquet và manifest; không dùng pickle làm nguồn dữ liệu.
- Hai baseline bắt buộc: zero-return và rolling-mean return 24 giờ.
- XGBoost, GRU và LSTM được định nghĩa/huấn luyện trước.
- Loader nhận đủ cả năm `model_type`; PatchTST/iTransformer model class được làm
  ở giai đoạn sau.

## 2. Nguyên tắc kiến trúc

1. `pipeline/batch/` tiếp tục sở hữu download, staging, DQ và load warehouse.
   `pipeline/decision/` chỉ điều phối backfill và đọc dữ liệu sạch từ DW; không
   viết một Binance downloader thứ hai.
2. Feature extractor 13 chiều chỉ có một implementation dùng chung.
3. Cùng một sample index, target và split cho cả năm model.
4. Sự khác nhau về input được đặt trong adapter, không copy feature logic vào
   từng model.
5. Scaler chỉ `fit` trên train. Validation/test chỉ được `transform`.
6. Test set cuối được khóa; không dùng để chọn feature, hyperparameter hoặc
   early stopping.
7. Artifact của một run là bất biến, có UUID và checksum; không ghi đè model cũ.
8. Pipeline direction classifier dummy hiện tại không phải ràng buộc thiết kế.
   Khi triển khai có thể thay thế/tách nó, nhưng không tái sử dụng contract Brier
   score của classifier cho bài toán hồi quy giờ.

Quy ước timestamp khi implement:

```text
latest_input_open_time = open_time của candle đầu vào cuối cùng t
cutoff_time = latest_input_open_time + 1 giờ
target_time = cutoff_time = open_time của candle t+1
```

Ví dụ nến đầu vào cuối mở lúc 10:00 và đóng lúc 11:00. Model chạy sau 11:00
để dự báo nến mở lúc 11:00. Không gán `cutoff_time` bằng 10:00.

## 3. Cấu trúc file đề xuất

```text
pipeline/decision/
├── __init__.py
├── cli.py
├── config.py
├── types.py
│
├── data/
│   ├── __init__.py
│   ├── warehouse_repository.py
│   ├── coverage.py
│   ├── backfill.py
│   ├── snapshot.py
│   ├── feature_extractor.py
│   ├── sample_index.py
│   ├── split.py
│   ├── scaler.py
│   ├── input_adapters.py
│   └── dataloader.py
│
├── models/
│   ├── __init__.py
│   ├── factory.py
│   ├── xgboost_regressor.py
│   ├── recurrent_regressor.py
│   ├── patchtst_regressor.py       # phase sau
│   └── itransformer_regressor.py   # phase sau
│
├── training/
│   ├── __init__.py
│   ├── seed.py
│   ├── early_stopping.py
│   ├── xgboost_trainer.py
│   ├── torch_trainer.py
│   └── run_training.py
│
├── evaluation/
│   ├── __init__.py
│   ├── baselines.py
│   ├── metrics.py
│   ├── evaluator.py
│   ├── backtest.py
│   └── report.py
│
├── artifacts/
│   ├── __init__.py
│   ├── manifest.py
│   ├── store.py
│   └── registry.py
│
└── inference/                     # sau khi training/evaluation ổn định
    ├── __init__.py
    ├── predictor.py
    └── forecast_repository.py

tests/decision/forecasting/
├── test_coverage.py
├── test_backfill.py
├── test_snapshot.py
├── test_feature_extractor.py
├── test_sample_index.py
├── test_split.py
├── test_scaler.py
├── test_input_adapters.py
├── test_dataloader.py
├── test_xgboost_regressor.py
├── test_recurrent_regressor.py
├── test_baselines.py
├── test_metrics.py
├── test_evaluator.py
├── test_backtest.py
└── test_training_smoke.py
```

Không cần tạo tất cả file rỗng ngay. Tạo theo phase ở mục 17 để mỗi commit đều
chạy được và có test.

## 4. Kiểu dữ liệu và cấu hình chung

### `pipeline/decision/types.py`

```python
class ModelType(str, Enum):
    XGBOOST = "xgboost"
    GRU = "gru"
    LSTM = "lstm"
    PATCHTST = "patchtst"
    ITRANSFORMER = "itransformer"

class DatasetSplit(str, Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"

@dataclass(frozen=True)
class SplitBoundaries:
    validation_start: datetime
    test_start: datetime
    test_end: datetime

@dataclass(frozen=True)
class SampleMetadata:
    symbol: str
    latest_input_open_time: datetime
    cutoff_time: datetime
    target_time: datetime
    reference_close_usdt: float
    actual_close_usdt: float

@dataclass(frozen=True)
class PredictionResult:
    metadata: SampleMetadata
    predicted_log_return: float
    predicted_close_usdt: float
    model_type: ModelType
    run_id: str
```

`ModelType` là đầu vào duy nhất để model factory và data loader quyết định layout.
Không truyền string rải rác trong code.

### `pipeline/decision/config.py`

Các dataclass:

- `ForecastDataConfig`: source, symbols, start time từng coin, snapshot cutoff,
  lookback, horizon, feature version.
- `XGBoostConfig`: toàn bộ tham số `XGBRegressor` và early stopping.
- `RecurrentConfig`: cell type, input size, hidden size, layers, dropout.
- `TrainingConfig`: batch size, epochs, learning rate, patience, seed, device.
- `BacktestConfig`: fold boundaries, refit policy và minimum samples.
- `ArtifactConfig`: snapshot root, run root và report root.

Giá trị nghiệp vụ được thêm vào `pipeline/settings.yaml`:

```yaml
forecasting:
  symbols: [BTC, ETH, SOL]
  source_code: binance
  feature_version: hourly-return-v1
  lookback_hours: 168
  horizon_hours: 1
  validation_start: "2025-01-01T00:00:00Z"
  test_start: "2026-01-01T00:00:00Z"
  seeds: [42, 123, 2026]
  rolling_baseline_hours: 24
```

Đường dẫn máy/container không ghi cứng trong YAML. Đọc từ biến môi trường:

```text
FORECAST_SNAPSHOT_DIR=data/forecasting/snapshots
FORECAST_RUN_DIR=data/forecasting/runs
```

## 5. Backfill và kiểm tra độ phủ dữ liệu

Backfill phải đi qua flow hiện tại:

```text
Binance archive
→ pipeline.batch.ingest_binance_history
→ staging.stg_ohlcv
→ pipeline.batch.warehouse_loader
→ DQ/meta
→ dw.fact_ohlcv_hourly
→ coverage audit lần hai
```

### `data/warehouse_repository.py`

`HourlyCandleRepository` chỉ đọc DW và trả schema ổn định:

```python
class HourlyCandleRepository:
    def fetch_candles(
        self, symbol: str, start: datetime, end: datetime
    ) -> pd.DataFrame: ...

    def fetch_coverage(
        self, symbols: Sequence[str], start: datetime, end: datetime
    ) -> pd.DataFrame: ...

    def fetch_source_batch_ids(
        self, symbol: str, start: datetime, end: datetime
    ) -> list[int]: ...
```

`fetch_candles()` phải:

- Join `dim_asset` và `dim_source`.
- Lọc chính xác `source_code='binance'` và một symbol.
- Dùng khoảng nửa mở `[start, end)`.
- Sort `open_time` tăng dần.
- Trả OHLC, `volume_quote`, `trade_count`, `batch_id`, `loaded_at`.
- Không impute hoặc tự xóa duplicate âm thầm.

### `data/coverage.py`

```python
@dataclass(frozen=True)
class CoverageReport:
    symbol: str
    requested_start: datetime
    requested_end: datetime
    first_candle: datetime | None
    last_candle: datetime | None
    row_count: int
    duplicate_count: int
    missing_ranges: tuple[TimeRange, ...]

class CoverageAuditor:
    def audit(self, candles: pd.DataFrame, start: datetime, end: datetime) -> CoverageReport: ...
    def assert_trainable(self, report: CoverageReport) -> None: ...
```

Mỗi coin có thể có ngày listing khác nhau. `requested_start` phải lấy từ config
từng coin; không coi thời gian trước listing là gap. Gap bên trong khoảng lịch sử
thì không được lấp bằng nội suy.

### `data/backfill.py`

```python
class BackfillService:
    def audit(self, symbols: Sequence[str], start: str, end: str) -> list[CoverageReport]: ...
    def backfill(self, symbols: Sequence[str], start_month: str) -> BackfillResult: ...
    def verify(self, before: Sequence[CoverageReport]) -> list[CoverageReport]: ...
```

`backfill()` không tải lại toàn bộ lịch sử. Luồng triển khai:

1. audit `dw.fact_ohlcv_hourly` trong khoảng yêu cầu và gom chính xác các giờ thiếu;
2. quy đổi gap cũ thành monthly archive, gap trong tháng hiện tại thành daily archive;
3. kiểm raw cache bằng checksum từ Binance và đối chiếu checksum đã load trong
   `meta.loaded_archive`;
4. chỉ stage các archive che phủ gap (archive mới, Binance đã sửa, hoặc archive
   cần stage lại để sửa gap dù checksum không đổi), với `replace=False`;
5. gọi `warehouse_loader.run(extract_batch_id=batch_id)` để DQ và UPSERT vào DW;
6. audit lại và báo số giờ thiếu trước/sau.

Nếu monthly archive của tháng trước chưa được Binance phát hành, chỉ các daily
archive giao với gap mới được dùng làm fallback. Gap của ngày UTC hiện tại được
đánh dấu `deferred_hours`, vì daily archive chỉ xuất hiện sau khi ngày kết thúc.
Kết quả lưu extract batch, load batch, row counts và phân loại archive
`new/changed/repaired/unavailable`. Job fail nếu load lỗi; không tạo snapshot từ
staging.

CLI:

```bash
python -m pipeline.decision.cli audit-data --symbols BTC,ETH,SOL
python -m pipeline.decision.cli backfill --symbols BTC --start 2020-01
```

## 6. Snapshot dữ liệu tái lập được

### `data/snapshot.py`

```python
class SnapshotBuilder:
    def build(
        self, symbol: str, start: datetime, cutoff: datetime
    ) -> DatasetSnapshot: ...

    def load(self, snapshot_id: str, symbol: str) -> DatasetSnapshot: ...

    def verify_hashes(self, snapshot: DatasetSnapshot) -> None: ...
```

Cấu trúc artifact:

```text
data/forecasting/snapshots/<snapshot_id>/<symbol>/
├── candles.parquet
├── features.parquet
├── samples.parquet
└── manifest.json
```

- `candles.parquet`: dữ liệu DW tại thời điểm snapshot.
- `features.parquet`: một row cho mỗi candle, gồm 13 feature chung.
- `samples.parquet`: sample index, target, split, reference/actual close và lý do
  loại nếu không hợp lệ; không lưu sẵn tensor `[N,168,13]`.
- `manifest.json`: snapshot ID, hash từng file, query/feature version, git commit,
  data cutoff, batch IDs, boundaries và rejection counts.

Không dùng `.pkl` cho dataset. Có thể cache tensor `.pt` hoặc `.npz` sau này,
nhưng cache phải xóa/tạo lại được từ snapshot.

## 7. Feature extractor chung

### `data/feature_extractor.py`

```python
BASE_FEATURES = (
    "log_return_1h",
    "open_close_return",
    "high_low_range",
    "close_position",
    "upper_wick",
    "lower_wick",
    "log_volume",
    "volume_change",
    "log_trade_count",
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
)

class HourlyFeatureExtractor:
    feature_version = "hourly-return-v1"

    def validate_candles(self, candles: pd.DataFrame) -> None: ...
    def transform(self, candles: pd.DataFrame) -> pd.DataFrame: ...
    def feature_names(self) -> tuple[str, ...]: ...
```

`transform()` chỉ tạo feature tại từng candle. Nó không biết XGBoost, RNN hay
Transformer. Quy tắc:

- Tính riêng theo symbol sau khi sort thời gian.
- `close_position=0.5` nếu `high==low`.
- Dùng quote volume (`volume_quote`).
- Thay `inf/-inf` thành invalid; không impute.
- Giữ `open_time`, `close_price` và `batch_id` làm metadata, không đưa chúng
  vào danh sách feature.
- Một thay đổi công thức phải tạo `feature_version` mới.

### `data/sample_index.py`

```python
class SampleIndexBuilder:
    def build(
        self,
        candles: pd.DataFrame,
        features: pd.DataFrame,
        lookback: int = 168,
        horizon: int = 1,
    ) -> pd.DataFrame: ...
```

Mỗi sample row chứa:

```text
sample_id, symbol
window_start_time, latest_input_open_time, cutoff_time, target_time
window_start_row, window_end_row, target_row
reference_close_usdt, actual_close_usdt, target_log_return
is_valid, rejection_reason
```

Một training sample chỉ hợp lệ khi toàn bộ `t-168 ... t+1` gồm 170 nến thô
liên tiếp. Lý do cần 170:

- `t-168`: chỉ để tính return/change của feature row đầu tiên.
- `t-167 ... t`: 168 feature rows được model nhìn thấy.
- `t+1`: tạo target.

Các `rejection_reason` tối thiểu: `missing_hour`, `duplicate_hour`,
`invalid_ohlc`, `invalid_feature`, `missing_target`, `unclosed_target`.

## 8. Split train/validation/test

### `data/split.py`

```python
class TimeSeriesSplitter:
    def assign(
        self, samples: pd.DataFrame, boundaries: SplitBoundaries
    ) -> pd.DataFrame: ...

    def expanding_folds(
        self, train_samples: pd.DataFrame, n_folds: int, gap_hours: int = 1
    ) -> Iterator[TimeFold]: ...

    def validate_no_leakage(self, samples: pd.DataFrame) -> None: ...
```

Split chính theo `target_time`:

```text
TRAIN       target_time < 2025-01-01 00:00 UTC
VALIDATION  2025-01-01 <= target_time < 2026-01-01 UTC
TEST        2026-01-01 <= target_time < snapshot_cutoff
```

Context validation/test được phép lấy các giờ quá khứ thuộc partition trước.
Đây không phải leakage vì các candle đó tồn tại tại cutoff. Ngược lại, target
hoặc scaler statistics không được vượt ranh partition.

Chiến lược sử dụng:

1. **Train folds:** expanding-window chỉ nằm trong TRAIN, dùng khi tune.
2. **Validation 2025:** early stopping, chọn hyperparameter/checkpoint và chọn
   candidate. Không chọn bằng TEST.
3. **Test 2026:** chạy đúng một lần sau khi code, feature và config đã khóa.
4. Nếu thay đổi thiết kế sau khi xem TEST, đánh dấu test đã bị dùng và phải dành
   một kỳ tương lai mới làm final holdout.

Không tự đổi boundaries khi thiếu dữ liệu; trả `insufficient_data` và yêu cầu
backfill.

## 9. Scaler và adapter theo model type

### `data/scaler.py`

```python
class SequenceScaler:
    def fit(self, train_features: np.ndarray) -> "SequenceScaler": ...
    def transform(self, features: np.ndarray) -> np.ndarray: ...
    def save(self, path: Path) -> None: ...
    @classmethod
    def load(cls, path: Path) -> "SequenceScaler": ...
```

V1:

- XGBoost không scale input.
- Bốn sequence model scale 13 feature theo từng cột.
- Fit scaler bằng toàn bộ timestep thuộc các sample TRAIN hợp lệ, nhưng tránh
  làm một candle lặp nhiều lần tạo trọng số ngoài ý muốn: fit trên feature rows
  duy nhất thuộc vùng train, rồi mới tạo window.
- Chưa scale target ở lần triển khai đầu; Huber loss nhận log-return thật.

### `data/input_adapters.py`

```python
class XGBoostInputAdapter:
    def transform(self, features: pd.DataFrame, samples: pd.DataFrame) -> TabularInputs: ...
    def feature_names(self) -> tuple[str, ...]: ...

class SequenceInputAdapter:
    def transform_one(self, sample: pd.Series) -> np.ndarray: ...

class PatchTSTInputAdapter(SequenceInputAdapter):
    def layout(self, window: np.ndarray) -> np.ndarray: ...  # [13, 168]
```

XGBoost adapter tạo:

- Giá trị hiện tại của 13 base feature.
- Lag `1,2,3,6,12,24,48,72,167` cho sáu series đã chốt.
- Momentum `6,12,24,72,168`.
- Volatility `6,24,72,168`, `ddof=0`.
- Volume z-score `24,168`; bằng 0 khi rolling std bằng 0.

Không dùng lag return 168 nếu nó yêu cầu candle trước giới hạn `t-168`.

Sequence adapter lấy đúng 168 row base feature. Không tự tính feature lần nữa.

## 10. Data loader chung cho năm model

### `data/dataloader.py`

Public entry point:

```python
class ForecastDataModule:
    def __init__(
        self,
        snapshot: DatasetSnapshot,
        model_type: ModelType,
        batch_size: int,
        seed: int,
        num_workers: int = 0,
    ): ...

    def setup(self) -> None: ...
    def tabular(self, split: DatasetSplit) -> TabularData: ...
    def dataloader(self, split: DatasetSplit, shuffle: bool | None = None) -> DataLoader: ...
    def metadata(self, split: DatasetSplit) -> pd.DataFrame: ...
    def input_shape(self) -> tuple[int, ...]: ...
```

Factory tiện dụng:

```python
def load_model_data(
    snapshot_id: str,
    symbol: str,
    model_type: ModelType,
    batch_size: int = 128,
) -> ForecastDataModule: ...
```

Mapping bắt buộc:

| `model_type` | API trainer dùng | Shape một batch |
| --- | --- | --- |
| `xgboost` | `module.tabular(split)` | `X=[N,F]`, `y=[N]` |
| `gru` | `module.dataloader(split)` | `X=[B,168,13]`, `y=[B,1]` |
| `lstm` | `module.dataloader(split)` | `X=[B,168,13]`, `y=[B,1]` |
| `patchtst` | `module.dataloader(split)` | `X=[B,13,168]`, `y=[B,1]` |
| `itransformer` | `module.dataloader(split)` | `X=[B,168,13]`, `y=[B,1]` |

Quy tắc shuffle:

- TRAIN có thể shuffle các **window đã tạo**, vì từng window vẫn giữ nguyên thứ
  tự 168 giờ bên trong.
- VALIDATION và TEST không shuffle để prediction/report giữ thứ tự thời gian.
- Không random split sample.
- `drop_last=False` cho evaluation.

Nếu gọi `tabular()` với sequence model hoặc `dataloader()` với XGBoost, raise
error rõ ràng thay vì tự chuyển đổi ngầm.

PatchTST/iTransformer loader và shape test được làm ngay trong phase data.
`models/factory.py` vẫn raise `NotImplementedError` cho hai model đó tới phase
Transformer.

## 11. Định nghĩa model giai đoạn đầu

### `models/xgboost_regressor.py`

```python
def build_xgboost_regressor(config: XGBoostConfig) -> XGBRegressor: ...

class XGBoostForecastModel:
    def fit(self, train: TabularData, validation: TabularData) -> TrainingHistory: ...
    def predict(self, data: TabularData) -> np.ndarray: ...
    def save(self, path: Path) -> None: ...
    @classmethod
    def load(cls, path: Path) -> "XGBoostForecastModel": ...
```

Cấu hình đầu tiên là cấu hình cố định trước khi tune:

```text
objective=reg:squarederror
eval_metric=mae
tree_method=hist
n_estimators=500
learning_rate=0.03
max_depth=3
min_child_weight=20
subsample=0.8
colsample_bytree=0.8
reg_alpha=0
reg_lambda=10
early_stopping_rounds=30
random_state=42
```

Lưu bằng format native `model.ubj`, kèm feature names/order trong manifest;
không pickle model XGBoost.

### `models/recurrent_regressor.py`

```python
class RecurrentRegressor(nn.Module):
    def __init__(
        self,
        cell_type: Literal["gru", "lstm"],
        input_size: int = 13,
        hidden_size: int = 64,
        num_layers: int = 1,
        dropout: float = 0.1,
    ): ...

    def forward(self, x: torch.Tensor) -> torch.Tensor: ...

class GRURegressor(RecurrentRegressor): ...
class LSTMRegressor(RecurrentRegressor): ...
```

Forward contract:

```text
[B,168,13]
→ nn.GRU hoặc nn.LSTM(batch_first=True)
→ hidden cuối [B,H]
→ dropout
→ Linear(H,1)
→ [B,1]
```

Không dùng bidirectional. Dropout bên trong recurrent layer chỉ bật khi
`num_layers > 1`; dropout trước regression head vẫn dùng được với một layer.

### `models/factory.py`

```python
def build_model(model_type: ModelType, config: ModelConfig):
    match model_type:
        case ModelType.XGBOOST: ...
        case ModelType.GRU: ...
        case ModelType.LSTM: ...
        case ModelType.PATCHTST | ModelType.ITRANSFORMER:
            raise NotImplementedError("Transformer models are phase 2")
```

## 12. Training

### `training/xgboost_trainer.py`

```python
class XGBoostTrainer:
    def fit(
        self, model: XGBoostForecastModel, data: ForecastDataModule
    ) -> TrainingResult: ...
```

- Fit TRAIN.
- Early stopping chỉ nhìn VALIDATION MAE.
- Ghi `best_iteration`, wall time và peak memory nếu đo được.
- Không đọc TEST trong trainer.

### `training/torch_trainer.py`

```python
class TorchTrainer:
    def fit(
        self, model: nn.Module, data: ForecastDataModule
    ) -> TrainingResult: ...

    def train_epoch(self, model, loader, optimizer) -> EpochMetrics: ...
    def validate_epoch(self, model, loader) -> EpochMetrics: ...
    def predict(self, model, loader) -> np.ndarray: ...
```

Cấu hình mặc định:

```text
loss=HuberLoss
optimizer=AdamW
learning_rate=1e-3
batch_size=128
gradient_clip_norm=1.0
early_stopping_patience=10
max_epochs=100
```

`EarlyStopping` theo validation MAE, lưu checkpoint tốt nhất chứ không phải
epoch cuối. GRU/LSTM chạy ba seed và báo mean ± std.

### `training/run_training.py`

```python
class TrainingOrchestrator:
    def run(
        self,
        symbol: str,
        model_type: ModelType,
        snapshot_id: str,
        seed: int,
    ) -> TrainingRun: ...
```

Flow:

```text
load/verify snapshot
→ create ForecastDataModule(model_type)
→ fit train-only scaler nếu cần
→ build model
→ train + early stop bằng validation
→ predict validation
→ compare baselines
→ save candidate run dù accepted hay rejected
```

Một run validation không tự động xem TEST.

## 13. Baseline, metric và evaluation

### `evaluation/baselines.py`

```python
def predict_zero_return(n_samples: int) -> np.ndarray: ...

def predict_rolling_mean_return(
    windows: np.ndarray, return_feature_index: int, hours: int = 24
) -> np.ndarray: ...
```

Baseline phải chạy trên đúng sample IDs của model. Không để baseline giữ các
sample mà model bị loại hoặc ngược lại.

### `evaluation/metrics.py`

```python
@dataclass(frozen=True)
class ForecastMetrics:
    mae_return: float
    rmse_return: float
    mae_price_usdt: float
    smape_price: float
    relative_mae: float | None
    directional_accuracy: float
    pearson: float | None
    spearman: float | None

def compute_metrics(
    actual_return: np.ndarray,
    predicted_return: np.ndarray,
    reference_close: np.ndarray,
    persistence_mae: float,
) -> ForecastMetrics: ...
```

Quy ước:

- `predicted_close = reference_close * exp(predicted_return)`.
- `sign(0)=0` khi tính directional accuracy.
- Relative MAE là `None` nếu persistence MAE bằng 0.
- Reject NaN/inf; không impute prediction.

### `evaluation/evaluator.py`

```python
class ModelEvaluator:
    def evaluate(
        self,
        model,
        data: ForecastDataModule,
        split: DatasetSplit,
    ) -> EvaluationReport: ...

    def evaluate_by_month(self, predictions: pd.DataFrame) -> pd.DataFrame: ...
    def decide_candidate(self, report: EvaluationReport) -> CandidateDecision: ...
```

Candidate qua validation khi:

- MAE toàn validation thấp hơn cả zero-return và rolling-mean baseline.
- Thắng zero-return ít nhất 7/12 tháng validation.
- Mỗi tháng được tính có ít nhất 500 sample hợp lệ.
- Không có gap/freshness/shape violation.

Nếu không đạt vẫn lưu report với status `rejected`; không xóa bằng chứng run.

## 14. Backtest và cách dùng test set

Trong dự án này cần phân biệt hai mức:

1. **Forecast backtest:** phát lại lịch sử theo thứ tự thời gian, tại mỗi cutoff
   chỉ dùng dữ liệu quá khứ rồi so dự báo với ground truth. Đây là phần bắt buộc.
2. **Trading strategy backtest:** chuyển forecast thành lệnh, tính fee, slippage,
   position sizing và PnL. Chưa làm ở V1 vì chưa có trading rule.

### `evaluation/backtest.py`

```python
class ForecastBacktester:
    def run_fixed_model(
        self,
        run_id: str,
        split: DatasetSplit,
    ) -> BacktestReport: ...

    def run_walk_forward(
        self,
        model_type: ModelType,
        folds: Sequence[TimeFold],
        frozen_config: ModelConfig,
    ) -> BacktestReport: ...
```

Hai chế độ:

- `run_fixed_model`: checkpoint đã chọn bằng validation được chạy tuần tự trên
  TEST. Đây là báo cáo holdout chính.
- `run_walk_forward`: thí nghiệm vận hành, expanding train window và refit tại
  đầu mỗi tháng/quý. Config phải được khóa trước; report tách riêng với fixed
  holdout để không nhập nhằng.

Quy trình mở khóa TEST:

```text
feature/config frozen
→ validation report accepted
→ tạo sealed-run marker
→ backtest TEST đúng một lần
→ lưu predictions.parquet + metrics.json
```

CLI yêu cầu `--sealed-run`; code không cho `train` nhận split TEST.

## 15. Artifact và model registry

### `artifacts/store.py`

```python
class ArtifactStore:
    def create_run(self, metadata: RunMetadata) -> RunPaths: ...
    def save_model(self, run: RunPaths, model) -> FileDigest: ...
    def save_scaler(self, run: RunPaths, scaler) -> FileDigest: ...
    def save_predictions(self, run: RunPaths, frame: pd.DataFrame) -> FileDigest: ...
    def finalize(self, run: RunPaths, manifest: RunManifest) -> None: ...
    def verify(self, run_id: str) -> None: ...
```

Cấu trúc:

```text
data/forecasting/runs/<symbol>/<model_type>/<run_id>/
├── model.ubj              # XGBoost
├── model.pt               # GRU/LSTM state_dict
├── scaler.json            # mean/std và feature order của sequence scaler
├── config.json
├── feature_names.json
├── training_history.json
├── validation_metrics.json
├── test_metrics.json      # chỉ xuất hiện sau sealed test
├── predictions.parquet
└── manifest.json
```

Checkpoint PyTorch lưu `state_dict` và config, không pickle nguyên object model.

### Database registry

Schema classifier dummy hiện có chứa các cột Brier/accuracy, không phù hợp với
forecast regression. Tạo migration riêng, ví dụ
`postgres/migrations/010_hourly_forecasting.sql`, thay vì nhét dữ liệu vào
contract cũ.

Các bảng dự kiến:

- `meta.forecast_training_run`: run ID, symbol, model type, snapshot ID,
  boundaries, config, status, timestamps và artifact checksum.
- `meta.forecast_evaluation`: run ID, split, metric name/value, period.
- `dw.dim_forecast_model`: model version được promote theo symbol/horizon.
- `dw.fact_hourly_forecast`: cutoff/target, predicted return/close, actual values
  khi đã có, model key và evaluated time.
- `meta.forecast_input_lineage`: forecast/run nối tới các `etl_batch` nguồn.

Migration/API integration chỉ làm sau khi offline pipeline và contract được test.

## 16. Kế hoạch test

“Test model” gồm hai việc khác nhau: test code bằng `pytest` và đánh giá trên
final TEST partition. Cả hai đều bắt buộc.

### Unit tests dữ liệu

- Feature công thức đúng với một chuỗi candle nhỏ tính tay được.
- Sửa candle tương lai không làm feature/sample quá khứ thay đổi.
- `high==low` tạo `close_position=0.5`.
- Gap một giờ loại mọi window cắt qua gap nhưng không loại window ngoài gap.
- Target đúng `log(close[t+1]/close[t])`.
- Sample đầu tiên dùng đúng 170 nến thô và 168 feature rows.
- Split đúng tại chính xác `2025-01-01` và `2026-01-01` UTC.
- Outlier chỉ nằm ở validation/test không thay đổi scaler đã fit từ train.

### Data loader contract tests

Với cùng một danh sách `sample_id`:

```text
xgboost       → [N,F] và [N]
gru/lstm      → [B,168,13] và [B,1]
patchtst      → [B,13,168] và [B,1]
itransformer  → [B,168,13] và [B,1]
```

Ngoài shape, assert window đầu/cuối và target của cả năm loader cùng trỏ tới
đúng sample metadata.

### Model tests

- XGBoost fit/predict/save/load trên dataset nhỏ; prediction trước/sau load bằng nhau.
- GRU/LSTM forward trả `[B,1]`, backward có gradient hữu hạn.
- Một training smoke test làm loss giảm trên dữ liệu synthetic đơn giản.
- Seed cố định tái lập được trong tolerance đã định.
- Factory raise rõ ràng cho Transformer chưa triển khai.

### Evaluation tests

- Zero-return luôn trả 0.
- Rolling mean chỉ đọc 24 return kết thúc tại cutoff.
- Metric kiểm bằng vector tính tay.
- Không chia 0 khi persistence MAE bằng 0.
- Evaluator dùng cùng sample IDs cho model và baseline.
- Trainer/evaluator validation không đọc TEST artifact.
- Sealed test chỉ chạy một lần cho cùng run ID.

### Backfill/integration tests

- Mock downloader để kiểm flow extract → staging → warehouse → audit.
- Backfill chạy lại không tạo duplicate fact rows.
- DQ fail thì snapshot không được tạo.
- Integration test với PostgreSQL kiểm query source/symbol/time boundaries.

## 17. Thứ tự triển khai

### Phase 0 — chốt contract và cấu hình

- Thêm `ModelType`, config và settings.
- Chốt start date từng coin và snapshot cutoff.
- Thêm dependencies dự kiến: `pyarrow`, `xgboost`, `torch`.

**Done khi:** config load được, validation lỗi rõ ràng, chưa cần model.

### Phase 1 — audit và backfill BTC

- Implement repository, coverage audit và backfill orchestrator.
- Backfill BTC đủ TRAIN/VALIDATION/TEST.
- Audit duplicate, missing ranges, first/last candle và DQ.

**Done khi:** DW có đủ dữ liệu BTC hoặc report chỉ chính xác gap còn thiếu.

### Phase 2 — snapshot, feature, sample và split

- Tạo immutable Parquet snapshot.
- Implement 13 feature, sample index, rejection report và time split.
- Test leakage/gap/boundary.

**Done khi:** cùng snapshot ID luôn tạo cùng checksum và sample counts.

### Phase 3 — loader cho cả năm model

- Implement scaler, XGBoost adapter, sequence adapter và `ForecastDataModule`.
- Implement đủ mapping shape cho năm `ModelType`.
- Chưa cần class Transformer.

**Done khi:** loader contract tests của cả năm model pass và sample IDs khớp.

### Phase 4 — baseline, metric và evaluator

- Implement hai baseline, metrics tổng/tháng và candidate rule.

**Done khi:** có validation report dù chưa có complex model.

### Phase 5 — XGBoost end-to-end

- Model, trainer, artifact store và CLI.
- Train BTC, so với baseline, lưu accepted/rejected report.

**Done khi:** chạy lại từ snapshot tạo kết quả tái lập trong tolerance và native
model load/predict được.

### Phase 6 — GRU và LSTM

- Recurrent model, Torch trainer, early stopping/checkpoint.
- Ba seed cho BTC; sau khi ổn định mở rộng ETH/SOL.

**Done khi:** validation report chứa mean ± std, latency và artifact size.

### Phase 7 — sealed test và forecast backtest

- Khóa feature/config.
- Chạy fixed-model TEST một lần.
- Báo cáo theo coin, tháng, model và baseline.

**Done khi:** có predictions + test metrics bất biến, không có tuning sau test.

### Phase 8 — registry, inference và hệ thống

- Migration cho hourly regression registry.
- Load champion per coin, kiểm freshness/gap, ghi forecast và lineage.
- Kết nối API/dashboard sau khi offline parity test pass.

### Phase 9 — Transformer

- Đọc/đối chiếu official code và paper.
- Implement `PatchTSTRegressor` rồi `ITransformerRegressor`.
- Tái sử dụng nguyên snapshot, split, scaler, loader, metrics và backtest.
- Chỉ thêm model config/head; không sửa target hoặc test set để ưu ái model mới.

## 18. CLI và Make targets dự kiến

```bash
# Data
make forecast-audit SYMBOLS=BTC,ETH,SOL
make forecast-backfill SYMBOLS=BTC START=2020-01
make forecast-dataset SYMBOL=BTC CUTOFF=2026-10-01T00:00:00Z

# Train/validation
make forecast-train SYMBOL=BTC MODEL=xgboost SEED=42
make forecast-train SYMBOL=BTC MODEL=gru SEED=42
make forecast-train SYMBOL=BTC MODEL=lstm SEED=42
make forecast-eval RUN_ID=<uuid> SPLIT=validation

# Chỉ khi run đã sealed
make forecast-backtest RUN_ID=<uuid> SPLIT=test

# Software tests
make test
```

`pipeline/decision/cli.py` nên có subcommands tương ứng thay vì mỗi module tự
tạo một kiểu argparse khác nhau.

## 19. Definition of Done cho MVP

MVP hoàn thành khi:

1. BTC được audit/backfill đủ ba partition từ warehouse.
2. Snapshot có checksum, batch lineage và rejection counts.
3. Một feature extractor chung tạo đúng 13 feature, không leakage.
4. Loader nhận năm model type và trả đúng layout.
5. XGBoost, GRU, LSTM train/evaluate/save/load được.
6. Mỗi model được so với hai baseline trên cùng sample IDs.
7. Validation dùng để chọn candidate; test chỉ chạy sau khi sealed.
8. Báo cáo có MAE/RMSE return, MAE/sMAPE price, relative MAE, directional
   accuracy, metric theo tháng, latency và artifact size.
9. Tất cả unit/integration/smoke tests pass.
10. Transformer có điểm tích hợp rõ ràng mà không cần viết lại data pipeline.

Sau khi MVP BTC đạt các điều kiện trên mới chạy cùng pipeline cho ETH/SOL.
Sau ETH/SOL mới bắt đầu PatchTST-based và iTransformer-based.
