# Implementation plan — daily forecast support tool

Trạng thái: đã triển khai; xem báo cáo tại `docs/forecast_support_implementation_report.md`.  
Cập nhật: 23/10/2026.

## 1. Mục tiêu

Thay forecast giờ giữ chỗ hiện tại bằng hệ thống hỗ trợ dự báo giá đóng cửa UTC
ngày kế tiếp. Public tool phục vụ agent phải trả về trong cùng một response:

1. point forecast `q50` và giá đóng cửa dự báo;
2. `q10/q50/q90` để mô tả uncertainty;
3. rolling backtest causal trên `N` ngày gần nhất;
4. thống kê thị trường trên `N` ngày gần nhất;
5. trend của `K` nến giờ đã đóng gần nhất;
6. freshness, coverage, lineage và model version đã dùng.

Đây là research/support signal, không phải lệnh mua bán. Tool không được che giấu
việc model không thắng zero-return về MAE trong một evaluation window.

## 2. Scope đã kiểm tra

### 2.1. Target assets

Scope public ban đầu là:

```text
BTC
ETH
```

Không mở SOL hoặc các coin khác trong phase này. Coin ngoài allowlist trả lỗi
validation rõ ràng; không dùng forecast BTC thay thế cho coin chưa có model.

### 2.2. Trạng thái artifact hiện tại

| Asset | Snapshot daily-v2 | Tested GRU run | Trạng thái phục vụ |
|---|---|---|---|
| BTC | Có | Có | Đã pin bundle `2026-10-23-direction-v1` |
| ETH | Có | Có | Đã pin bundle `2026-10-23-direction-v1` |
| SOL | Có | Có | Ngoài scope |

BTC run đang được pin:

```text
run_id: 107b4799-4ae1-460e-8d3c-60182d073552
frequency: 1d
feature_version: daily-return-v2
lookback: 90 ngày
horizon: 1 ngày
```

Run này có validation policy `direction-v1`; bundle vẫn ghi
`deployment_tier=research_support`, không biến support signal thành trading model.

ETH run riêng đang được pin:

```text
run_id: 2aee3ffb-3ffd-4508-9644-5a45cb145e23
snapshot_id: 20261023T000000Z-eab401ad1ed3
```

BTC và ETH có weight/scaler/feature order/checksum riêng; runtime không tái sử dụng
weight BTC cho ETH.

### 2.3. Context assets

BTC và ETH đều dùng cùng universe 11 coin, chỉ khác target đứng đầu feature order:

```text
BTC, ETH, ADA, ATOM, BCH, BNB, DOGE, ETC, LINK, LTC, TRX
```

Runtime không được lấy danh sách này từ `pipeline/settings.yaml`. Asset order và
feature order phải được đọc từ bundle đã pin (`feature_names.json`/`scaler.json`),
vì settings có thể thay đổi sau khi model được train.

## 3. Contract thời gian

Tất cả timestamp dùng UTC và khoảng nửa mở.

Ví dụ request lúc `2026-10-23T12:30Z`:

```text
latest fully closed daily candle: ngày 2026-10-22
daily cutoff:                    2026-10-23T00:00Z
target daily candle:             [2026-10-23T00:00Z, 2026-10-24T00:00Z)
target close time:               2026-10-24T00:00Z

latest fully closed hourly candle:
                                  [2026-10-23T11:00Z, 2026-10-23T12:00Z)
hourly cutoff:                    2026-10-23T12:00Z
```

Daily forecast và hourly trend có cutoff khác nhau và response phải ghi cả hai.
Không đưa partial daily candle hoặc partial hourly candle vào input.

## 4. Tính range cần thiết

Không backfill toàn bộ lịch sử. Mỗi request chỉ audit/sync dependency range cần cho
request đó.

### 4.1. Daily range

Với model hiện tại:

```text
feature warm-up = 90 ngày
lookback         = 90 ngày
horizon          = 1 ngày
```

Chỉ inference hiện tại cần khoảng 180 daily candles liên tục cho từng context asset.
Inference cộng rolling backtest `N` ngày cần xấp xỉ:

```text
warm-up + lookback + N + horizon
```

Code phải tính ranh inclusive/exclusive từ sample builder, không hardcode số dòng.
Range bắt đầu được mở rộng lùi về quá khứ; range kết thúc tại daily cutoff gần nhất.

### 4.2. Hourly range

Trend `K` giờ cần `K+1` closed hourly candles để tính đủ K hourly returns. Chỉ target
asset cần hourly range; các context asset không cần hourly data cho live trend.

### 4.3. Giới hạn public arguments

```text
performance_days: 7..365, default 30
market_days:      7..365, default 30
trend_hours:     24..1000, default 168
```

Data range thật sự là union của forecast, rolling performance, market statistics và
hourly trend. Không cho LLM/user truyền `backfill_start` tùy ý.

## 5. Audit trước, backfill sau

Đây là invariant bắt buộc:

```text
compute required ranges
→ audit DW
→ nếu complete: SKIP backfill
→ nếu incomplete: backfill chính xác missing ranges
→ audit lại
→ chỉ inference khi complete
```

### 5.1. Readiness report

```python
@dataclass(frozen=True)
class DataReadinessReport:
    daily_cutoff: datetime
    hourly_cutoff: datetime
    required_daily_symbols: tuple[str, ...]
    daily_range: TimeRange
    hourly_range: TimeRange
    missing_daily_ranges: dict[str, tuple[TimeRange, ...]]
    missing_hourly_ranges: dict[str, tuple[TimeRange, ...]]
    duplicate_rows: int
    invalid_rows: int
    is_complete: bool
```

Complete không chỉ là `max(open_time)` đã tới hiện tại. Phải đồng thời bảo đảm:

- đủ mọi timestamp trong expected grid;
- không trùng natural key;
- OHLC/volume/trade count hợp lệ;
- mọi context asset đủ cùng range;
- last candle đúng expected closed cutoff;
- source là Binance theo bundle contract.

Nếu `is_complete=true`, response readiness ghi:

```json
{
  "backfill_performed": false,
  "backfill_reason": "warehouse_already_complete"
}
```

và tuyệt đối không gọi downloader/staging/UPSERT.

### 5.2. Missing-range sync

Nếu thiếu dữ liệu:

1. map đúng missing ranges sang archive cần thiết;
2. kiểm raw cache và checksum đã load;
3. archive cũ dùng Binance archive ZIP;
4. recent tail chưa có archive dùng Binance REST klines;
5. stage với interval đúng (`1d` hoặc `1h`);
6. chạy DQ và UPSERT;
7. audit lại chính required range.

Không forward-fill, interpolate hoặc bỏ context coin bị thiếu. Nếu re-audit vẫn fail,
tool trả `insufficient_data`, không chạy model với tensor sai schema.

### 5.3. Concurrency và idempotency

- advisory/distributed lock theo `(frequency, symbol set, cutoff)`;
- request sau chờ hoặc dùng kết quả sync đang chạy, không tạo batch trùng;
- cache readiness theo cutoff;
- checksum và UPSERT giữ retry idempotent;
- giới hạn số archive/request và timeout;
- ghi batch IDs vào output lineage.

Vì on-demand sync có thể ghi DW, tool không được khai báo `readOnlyHint=true` một cách
sai lệch. Agent không quyết định range; internal service tính range cố định từ bundle
và arguments đã giới hạn.

## 6. Model serving bundle

Không serve trực tiếp từ một run directory tùy ý. Mỗi target có bundle bất biến:

```text
data/models/daily-forecast/<SYMBOL>/<VERSION>/
├── serving_manifest.json
├── model.pt
├── model_config.json
├── scaler.json
├── target_scaler.json
├── feature_names.json
├── offline_metrics.json
└── artifact_checksums.json
```

`serving_manifest.json` chứa tối thiểu:

```text
model_id, model_version, run_id, symbol
frequency, feature_version, lookback_periods, horizon_periods
asset_order, feature_names
snapshot_id, git_commit, seed
artifact SHA-256
offline validation/test metrics
deployment_tier=research_support
```

Loader fail nếu checksum, input size, feature order hoặc scaler không khớp.

## 7. Daily inference

Tái sử dụng `ForecastPredictor` và feature code hiện tại; không định nghĩa lại feature
trong agent package.

Output model:

```text
q10/q50/q90 log-return
q10/q50/q90 predicted close
direction từ sign(q50)
interval_crosses_zero = q10 <= 0 <= q90
interval_width = q90 - q10
```

Chuyển return thành close:

```text
q_price = reference_close × exp(q_return)
```

Không gọi nominal quantile interval là “80% chắc chắn”. Trả empirical coverage từ
evaluation window để agent diễn giải.

## 8. Rolling backtest causal N ngày

Không cần đợi hệ thống chạy N ngày. Với mỗi realized target day `t`:

```text
input:  candles đã đóng đến t-1
output: q10[t], q50[t], q90[t]
label:  actual close/return của t
```

Model, feature scaler và target scaler đều giữ frozen. Không refit trên rolling window.
Không feed predicted close ngày trước vào ngày sau; mỗi sample neo vào actual close đã
tồn tại tại cutoff của chính sample đó.

Các sample được build một lần và infer theo batch `[N,90,feature_count]`, không load
model N lần.

Metric:

```text
sample_count
mae_return, rmse_return, mae_price_usdt
directional_accuracy
zero_return_mae, relative_mae
q10/q90 empirical coverage
mean interval width
pinball loss q10/q50/q90
first_target_day, last_target_day
```

Response phải ghi:

```json
{
  "kind": "rolling_backtest",
  "causal": true,
  "prospective": false
}
```

Nếu model đã được tune sau khi nhìn giai đoạn này, đây không phải unseen test. Data
warehouse cũng chưa phải point-in-time snapshot cho từng ngày lịch sử. Hai limitation
này phải có trong response/skill, nhưng không ngăn metric được dùng như operational
recent-history diagnostic.

## 9. Market statistics N ngày

Backend tính deterministic, không gửi raw candles cho LLM tự tính:

```text
cumulative/log return
mean/median daily return
realized volatility
annualized volatility (365 ngày cho crypto)
maximum drawdown
highest/lowest close
average quote volume và volume change
average high-low range
up/down day count và up-day ratio
```

Mọi số liệu kèm `first_day`, `last_day`, `sample_count` và source lineage.

## 10. Hourly trend K candles

Hồi quy trên log close:

```text
x = 0..K-1
y = log(close)
y = intercept + slope × x
```

Trả:

```text
slope_per_hour
regression_r_squared
cumulative_return
up_candle_ratio
realized_volatility
maximum_drawdown
close_vs_ema_24h
close_vs_ema_168h (chỉ khi K đủ)
direction = sign(slope)
```

`R²` bắt buộc đi cùng slope; slope dương với `R²` thấp là trend yếu/nhiễu. Đây là
hourly closed-candle signal, không phải tick/second realtime signal.

## 11. Public tool contract

Tên mới:

```python
forecast_support(
    symbol: Literal["BTC", "ETH"] = "BTC",
    performance_days: int = 30,
    market_days: int = 30,
    trend_hours: int = 168,
    cutoff: str | None = None,
) -> dict
```

Không giữ tên `predict_hourly` cho output daily. Desk command `/predict BTC|ETH` có
thể giữ, nhưng backend operation phải là `forecast_support` hoặc `predict_daily`.

Response top-level:

```text
status: ready | refresh_pending | insufficient_data | stale | unavailable
observed_at
forecast
recent_performance
market_statistics
hourly_trend
data_readiness
model
limitations
```

Không trả toàn bộ N daily/K hourly candles cho LLM. Tool output chỉ chứa aggregate và
tối đa vài timestamp/lineage identifiers, giữ evidence bounded.

ETH khi chưa có bundle trả:

```json
{
  "status": "unavailable",
  "symbol": "ETH",
  "reason": "no_pinned_model_bundle"
}
```

Không fallback sang BTC.

## 12. File/class/method plan

### 12.1. Serving package mới

```text
pipeline/decision/serving/
├── contracts.py
├── model_bundle.py
├── data_readiness.py
├── rolling_evaluation.py
├── market_statistics.py
├── daily_forecast_service.py
└── support_service.py
```

```python
class ForecastModelBundle:
    load(symbol: str, version: str | None = None)
    verify_checksums()
    required_symbols()
    build_predictor(device="cpu")

class ForecastDataReadinessService:
    required_ranges(bundle, performance_days, market_days, trend_hours, cutoff)
    audit(requirements)
    plan_missing(readiness)
    sync_missing(plan)
    ensure_ready(...)

class RollingEvaluationService:
    build_samples(...)
    predict_batch(bundle, samples)
    evaluate(predictions)

class MarketStatisticsService:
    daily_statistics(symbol, days, cutoff)
    hourly_trend(symbol, hours, cutoff)

class DailyForecastService:
    predict(bundle, daily_frames, cutoff)

class ForecastSupportService:
    report(symbol, performance_days, market_days, trend_hours, cutoff)
```

Model loading nên tách khỏi `pipeline/decision/cli.py`; serving code không import CLI.

### 12.2. Data pipeline

Mở rộng backfill hiện tại thành period-aware hoặc tạo service mới hỗ trợ cả `1d` và
`1h`. Giữ flow raw cache → staging → DQ → DW UPSERT. Bổ sung REST-tail loader cho
closed periods chưa có archive.

### 12.3. Agent/A2A/MCP

Sửa:

```text
agents/prediction.py
agents/server.py
agents/gateway.py
warehouse_agents/tools.py
warehouse_agents/graph.py
warehouse_agents/desk.py
warehouse_agents/skills/forecast-explainer/SKILL.md
```

- `agents/prediction.py`: bỏ frozen hourly CatBoost implementation, gọi support service;
- `agents/server.py`: request contract nhận BTC/ETH và support parameters;
- `warehouse_agents/tools.py`: expose structured `forecast_support`;
- graph: allowlist/schema/routing mới;
- desk/skill: nói rõ “next UTC daily close”, quantile và rolling backtest.

Giữ hourly model/bundle cũ trong một release để rollback, nhưng không expose nó dưới
daily response.

## 13. ETH prerequisite (đã hoàn tất)

Trước khi bật `ETH`:

1. audit/sync snapshot range cần thiết;
2. rebuild immutable ETH snapshot nếu source tail thay đổi;
3. train GRU cùng approved architecture/config;
4. chạy validation/test report;
5. xác nhận quantile output và reload parity;
6. pin một ETH run riêng;
7. tạo ETH serving bundle và checksum;
8. chạy inference parity test;
9. sau đó mới thêm ETH bundle vào active registry.

Việc ETH model có metric kém không chặn research deployment nếu đó là quyết định sản
phẩm, nhưng status/reasons và baseline comparison phải được giữ trong manifest/tool.

## 14. Test plan

### Data readiness

- warehouse đủ đến cutoff → downloader/staging không được gọi;
- thiếu một daily/hourly range → chỉ range đó được sync;
- request lặp lại → không tạo batch mới;
- missing context asset → inference bị chặn;
- recent tail dùng REST, old gap dùng archive;
- re-audit fail → `insufficient_data`.

### Inference

- artifact checksum và feature order;
- BTC/ETH dùng model riêng;
- cùng cutoff cho output deterministic;
- sửa candle sau cutoff không đổi prediction;
- gap/duplicate/non-finite input bị từ chối;
- `q10 <= q50 <= q90` sau inverse scaling;
- online prediction khớp saved snapshot inference trong tolerance.

### Rolling evaluation

- mỗi sample chỉ đọc tới `t-1`;
- không recursive-feed prediction;
- scaler không fit lại;
- batch predictions align đúng target day;
- baseline dùng cùng sample set;
- N lớn hơn history khả dụng trả sample count/limitation rõ ràng.

### Tool/agent

- chỉ BTC/ETH;
- ETH chưa bundle trả unavailable;
- response schema và numeric values finite;
- output bounded, không raw candle dump;
- unavailable dependency không sinh forecast giả;
- trace ghi rõ audit, sync, inference và aggregation latency.

## 15. Trình tự triển khai

1. Pin BTC candidate run và tạo serving bundle.
2. Tách model loader khỏi CLI; thêm bundle verifier.
3. Implement daily/hourly readiness audit không mutation.
4. Implement targeted archive/REST sync và bắt buộc re-audit.
5. Implement BTC daily inference service.
6. Implement rolling backtest N ngày theo batch.
7. Implement market statistics và hourly trend.
8. Implement `forecast_support` contract và A2A/MCP wiring.
9. Đổi `/predict BTC` sang daily support response.
10. Train/test/pin ETH, rồi bật `/predict ETH`.
11. Chạy dual runtime/rollback test, sau đó retire public `predict_hourly`.

## 16. Definition of Done

- public tool chỉ nhận BTC/ETH;
- BTC và ETH không dùng chung target model weights;
- audit luôn chạy trước sync;
- complete warehouse tuyệt đối không backfill;
- incomplete warehouse chỉ sync exact missing ranges và re-audit;
- model input lấy đúng symbol/order/window từ bundle;
- forecast daily có q10/q50/q90 và timestamp rõ ràng;
- recent performance là causal rolling backtest và được ghi đúng nhãn;
- market statistics/hourly trend deterministic, không do LLM tự tính;
- mọi artifact/input/output có lineage/checksum;
- thiếu dữ liệu/model/dependency trả trạng thái rõ ràng, không fallback hoặc bịa số;
- có rollback về service cũ trong release đầu tiên.
