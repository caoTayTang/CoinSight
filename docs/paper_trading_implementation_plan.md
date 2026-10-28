# Implementation plan — deterministic trade decision và paper-trading dashboard

Trạng thái: **đề xuất để review, chưa triển khai**.  
Cập nhật: 27/10/2026.

## 1. Mục tiêu

Mở rộng daily forecast support hiện tại thành một hệ thống hỗ trợ quyết định và mô
phỏng giao dịch, không kết nối sàn và không sử dụng tiền thật:

```text
forecast_support
  → deterministic decision policy
  → BUY / SELL / HOLD / NO_TRADE
  → user xác nhận
  → paper execution
  → append-only trading ledger
  → dashboard và Trade Agent giải thích
```

Hệ thống phải phân biệt rõ:

- model tạo forecast và quantile;
- policy code tạo quyết định;
- paper executor mô phỏng khớp lệnh;
- LLM chỉ chọn tool và giải thích evidence, không tự nghĩ ra lệnh hoặc sửa rule;
- UI/API là nơi user xác nhận mutation.

Anomaly model không nằm trong flow này. Input chỉ dùng forecast, rolling model
performance, market statistics, hourly trend và portfolio state.

## 2. Scope v1

### Trong scope

- BTC và ETH, cặp spot `BTCUSDT`/`ETHUSDT`;
- target daily close UTC kế tiếp từ `forecast_support`;
- portfolio tiền ảo theo từng user;
- long-only: mua, giữ, giảm hoặc đóng vị thế;
- slippage mô phỏng; không mô phỏng trading fee trong scope hiện tại;
- advisory trước, manual paper execution sau;
- dashboard portfolio, decision, trade history, PnL và risk;
- backtest/walk-forward policy trước khi bật execution.

### Ngoài scope

- tiền thật, API key sàn và gửi order ra Binance;
- short, margin, futures, leverage;
- market making hoặc intraday strategy;
- tự retrain forecast model;
- để LLM tự quyết định position size hoặc bypass risk gate;
- anomaly model hoặc sentiment/news chưa có contract causal.

## 3. Nguyên tắc bắt buộc

1. **Deterministic và versioned:** cùng evidence + portfolio + policy version phải
   cho cùng decision.
2. **Causal:** chỉ đọc dữ liệu đã đóng và được biết tại `decision_time`.
3. **Fail closed:** thiếu/stale forecast, giá execution hoặc portfolio state thì
   trả `NO_TRADE`; không tự điền số liệu.
4. **Idempotent:** refresh/click lại không tạo order trùng.
5. **User isolation:** mọi portfolio/order phải gắn `user_key`; query luôn filter
   theo user đã xác thực từ server.
6. **Append-only evidence:** không sửa lại decision/fill lịch sử khi model hoặc
   rule thay đổi.
7. **No test tuning:** chọn rule/threshold trên train + validation; test chỉ mở
   một lần để báo cáo cuối.
8. **No probability claim:** `support_score` là điểm rule 0–1, không gọi là xác
   suất thắng nếu chưa calibration.

## 4. Contract decision

### 4.1. Input

```python
@dataclass(frozen=True)
class TradeDecisionRequest:
    user_key: str
    portfolio_id: UUID
    symbol: Literal["BTC", "ETH"]
    policy_version: str
    performance_days: int = 30
    market_days: int = 30
    trend_hours: int = 168
    cutoff: datetime | None = None
```

Đây là contract nội bộ. Public tool schema **không có `user_key`**: tool lấy identity
từ `warehouse_agents.run_context.CURRENT_USER`, vốn được A2A server gắn từ user đã
xác thực. API lấy identity bằng `Depends(current_user)`. User/LLM cũng không được
truyền trực tiếp q10/q50/q90 hoặc metric giả vào policy; service tự gọi
`forecast_support`.

Evidence snapshot tối thiểu:

- forecast return/close q10, q50, q90;
- reference close, daily cutoff và target close;
- recent directional accuracy, sample count và relative MAE;
- volatility, momentum, volume/liquidity và drawdown từ `market_statistics`;
- hourly trend đến latest closed hour;
- data freshness/readiness, model ID/version/checksum;
- cash, position, average entry, exposure và current equity;
- giá spot từ latest fully closed 1-minute candle dùng để định giá hiện tại.

### 4.2. Output

```json
{
  "decision_id": "uuid",
  "status": "ready",
  "action": "BUY | SELL | HOLD | NO_TRADE",
  "support_score": 0.72,
  "target_position_fraction": 0.10,
  "order_notional_usdt": 1000.0,
  "valid_until": "...",
  "policy": {"id": "daily-quantile", "version": "v1", "sha256": "..."},
  "forecast": {"model_id": "...", "model_version": "...", "target_close": "..."},
  "reasons": ["q10_and_q50_above_zero", "hourly_trend_aligned"],
  "risk_flags": [],
  "evidence_sha256": "...",
  "executable": true
}
```

`NO_TRADE` khác `HOLD`:

- `NO_TRADE`: evidence không đủ, stale, risk gate chặn hoặc score không đáng tin;
- `HOLD`: evidence hợp lệ và policy chủ động giữ vị thế hiện tại.

## 5. Decision policy v1

### 5.1. Pipeline

```text
validate contract
→ freshness/readiness gates
→ portfolio/risk gates
→ normalize deterministic signals
→ calculate bullish/bearish support
→ choose target position
→ convert target-position delta to BUY/SELL/HOLD
→ persist immutable decision + evidence
```

### 5.2. Signal components

Policy không cộng trực tiếp giá q10/q50/q90. Chúng được đổi thành các component có
range rõ ràng:

| Component | Ý nghĩa |
|---|---|
| `median_direction` | dấu và độ lớn của q50 return |
| `interval_position` | q10/q90 nằm cùng phía hay cắt zero-return |
| `direction_reliability` | directional accuracy với sample count/coverage |
| `trend_alignment` | daily forecast có cùng hướng hourly trend hay không |
| `momentum` | cumulative daily return chuẩn hóa bằng realized volatility |
| `up_day_balance` | tỷ lệ ngày tăng so với 50% |
| volatility/drawdown gates | volatility/drawdown cao làm giảm score, không tự đổi hướng |
| `model_error_warning` | relative MAE không thắng baseline là warning/size penalty |

Không coi q10–q90 là guaranteed 80% interval. Không suy ra confidence bằng
`q10 + q50 + q90`.

### 5.3. Action semantics

- `BUY`: target position lớn hơn current position;
- `SELL`: giảm/đóng long hiện có, không mở short;
- `HOLD`: target position gần current position trong rebalance tolerance;
- `NO_TRADE`: contract/readiness/freshness/risk gate không cho phép đánh giá;
- score dưới ngưỡng nhưng evidence hợp lệ tạo `HOLD`, không phải `NO_TRADE`.

### 5.4. Risk gates

Config versioned, không hardcode rải rác trong code:

```json
policy_id: daily-quantile
version: v1-research
mode: long_only_spot
min_performance_samples: 14
trade_threshold: 0.25
max_asset_fraction: 0.35
max_order_fraction: 0.15
max_annualized_volatility: 2.0
max_market_drawdown_fraction: 0.50
max_portfolio_drawdown_fraction: 0.25
rebalance_tolerance: 0.02
slippage_bps: 5.0
max_price_age_seconds: 300
```

Đây là config heuristic cho paper-only và được checksum trong mỗi decision; chưa
được xem là threshold đã validation cho giao dịch thật.

## 6. Backtest và acceptance của policy

### 6.1. Dữ liệu

Replay từng historical cutoff theo đúng flow causal:

- model input chỉ đến cutoff;
- q10/q50/q90 phải là prediction tạo tại cutoff đó;
- market statistics/hourly trend chỉ dùng dữ liệu đã biết;
- fill dùng candle kế tiếp sau decision time;
- slippage được áp dụng ở từng fill; không mô phỏng fee;
- không dùng test để chọn threshold.

### 6.2. Split

Giữ chronological train/validation/test, thêm walk-forward validation. Không dùng
random split hoặc trộn các regime tương lai vào train.

### 6.3. Baselines

- all cash;
- buy-and-hold theo từng asset;
- rebalance buy-and-hold BTC/ETH;
- naive sign(q50) với fixed size, không filter;
- policy hiện tại sau slippage.

### 6.4. Metrics

- cumulative/net return;
- annualized volatility, Sharpe và Sortino;
- maximum drawdown và recovery time;
- turnover và slippage cost;
- win rate, profit factor, average win/loss;
- exposure và trade coverage;
- directional accuracy chỉ trên samples policy thực sự trade;
- performance theo tháng/regime và BTC/ETH riêng;
- number of trades để tránh kết luận từ sample quá nhỏ.

Acceptance không chỉ dựa trên return cao. Policy phải có drawdown/risk hợp lý,
không phụ thuộc một seed và không sụp sau slippage.

## 7. Database design

Migration mới: `postgres/migrations/012_paper_trading.sql`.

### 7.1. Tables

```text
paper.portfolio
  portfolio_id, user_key, name, initial_cash_usdt,
  mode(advisory|manual), status, created_at, updated_at, version

paper.decision
  decision_id, portfolio_id, symbol, cutoff, target_close,
  policy_id/version/hash, model_id/version, action, support_score,
  target_position_fraction, order_notional, reasons, risk_flags,
  evidence, evidence_sha256, valid_until, created_at

paper.paper_order
  order_id, decision_id, portfolio_id, symbol, side,
  requested_notional_usdt, idempotency_key, status, created_at

paper.fill
  fill_id, order_id, quantity, market_price, fill_price, notional, slippage_bps,
  source, source_candle_time, executed_at

paper.equity_snapshot
  portfolio_id, observed_at, cash_usdt, positions_value_usdt, equity_usdt,
  realized_pnl_usdt, drawdown, source
```

### 7.2. Views

```text
paper.trade_history
```

### 7.3. Invariants

- unique decision theo portfolio + symbol + target + policy/model version;
- unique `idempotency_key` cho order;
- fill quantity/price/notional dương;
- không cho cash âm hoặc position âm trong long-only mode;
- order/fill transaction khóa row portfolio để chống double click;
- user chỉ đọc/ghi portfolio của chính mình;
- anonymous visitor không được tạo persistent paper portfolio.

## 8. File/class/method plan

### 8.1. Decision và execution domain

```text
pipeline/decision/trading/
├── __init__.py
├── contracts.py
├── policy.py
├── policy_store.py
├── decision_service.py
├── repository.py
├── backtest.py
├── report.py
└── policies/daily_quantile_v1.json
```

| File | Thành phần chính |
|---|---|
| `contracts.py` | `TradeDecisionRequest`, `TradeDecision`, `PaperOrderRequest`, `PortfolioSummary` |
| `policy.py` | `DailyQuantilePolicy.evaluate(evidence, portfolio)`; không I/O |
| `policy_store.py` | load JSON, validate và checksum immutable policy |
| `decision_service.py` | lấy portfolio, evaluate/persist decision, preview/execute |
| `repository.py` | query parameterized, accounting, execution, user isolation và transaction/row lock |
| `backtest.py` | causal replay trên các forecast-support observation đã được đóng băng |
| `report.py` | ghi JSON/CSV backtest artifacts |

Methods trọng tâm:

```python
DailyQuantilePolicy.evaluate(evidence, portfolio) -> TradeDecisionDraft
TradeDecisionService.create(request) -> TradeDecision
TradeDecisionService.preview(user_key, portfolio_id, decision_id) -> OrderPreview
TradeDecisionService.execute(user_key, portfolio_id, decision_id, idempotency_key) -> Fill
PaperTradingRepository.portfolio(user_key, portfolio_id) -> PortfolioState
PolicyBacktester.run(policy, start, end, symbols) -> BacktestReport
```

### 8.2. Agent tool

Sửa:

- `warehouse_agents/tools.py`: thêm `trade_decision(...)` read-only/advisory;
- `warehouse_agents/action_contracts.py`: strict schema BTC/ETH và bounded windows;
- `warehouse_agents/graph.py`: map tool cho `ANALYST`, mô tả LLM chỉ được giải thích;
- `warehouse_agents/run_context.py`: tái sử dụng `CURRENT_USER`, không expose identity trong schema;
- `warehouse_agents/skills/market-brief/SKILL.md`: thứ tự forecast → decision;
- `warehouse_agents/grounding.py`/guardrails nếu cần: BUY/SELL phải có decision evidence.

`trade_decision` public arguments chỉ gồm portfolio ID, symbol, bounded windows và
cutoff; user key lấy server-side. Không expose `paper_execute` cho LLM trong v1.
Mutation đi qua authenticated API và explicit UI confirmation.

### 8.3. API

Tạo `app/paper_trading.py`, sửa `app/api.py` và `app/api_schemas.py`:

```text
POST /v1/paper/portfolios
GET  /v1/paper/portfolios
GET  /v1/paper/portfolios/{id}
POST /v1/paper/portfolios/{id}/decisions
GET  /v1/paper/portfolios/{id}/decisions/latest?symbol=BTC
POST /v1/paper/portfolios/{id}/orders/preview
POST /v1/paper/portfolios/{id}/orders
GET  /v1/paper/portfolios/{id}/orders
GET  /v1/paper/portfolios/{id}/equity
GET  /v1/paper/portfolios/{id}/performance
```

Mọi endpoint dùng `Depends(current_user)`. Order request chỉ nhận `decision_id` và
`idempotency_key`; không tin price/quantity từ browser. Server tính lại từ decision,
portfolio và execution candle.

### 8.4. Frontend

Tạo:

```text
frontend/src/trading/
├── TradingDashboard.jsx
├── DecisionCard.jsx
├── OrderPreview.jsx
├── PortfolioSummary.jsx
├── PositionTable.jsx
├── EquityCurve.jsx
├── TradeHistory.jsx
├── RiskPanel.jsx
└── tradingApi.js
```

Sửa `frontend/src/App.jsx` để thêm workspace `Paper Trade` cho user đã đăng nhập.

Dashboard gồm:

1. cash/equity/PnL/drawdown/exposure;
2. current BTC/ETH positions;
3. forecast q10/q50/q90 và target timestamp;
4. decision, support score, reasons và risk flags;
5. preview order trước khi confirm;
6. trade history và fill details;
7. equity curve và benchmark buy-and-hold;
8. model/policy version, freshness và evidence link.

V1 dùng REST polling/manual refresh. Không cần WebSocket trading riêng; existing
market WebSocket chỉ cung cấp giá hiển thị, không phải execution authority.

## 9. Execution price và accounting

Manual order được fill bằng latest fully closed one-minute candle tại thời điểm confirm
và không quá freshness limit. `close_price` là reference fill trước
slippage:

```text
BUY fill  = close × (1 + slippage_bps / 10000)
SELL fill = close × (1 - slippage_bps / 10000)
```

Không có trading fee trong công thức v1 theo quyết định scope hiện tại.

Không dùng predicted close làm fill price. Không dùng partial candle. Source candle,
batch/source và observed time phải được ghi trong `paper.fill`.

## 10. Scheduler và auto-paper phase

Không làm auto mode ngay trong phase đầu. Sau khi manual paper ổn định:

- tạo `pipeline/decision/trading/worker.py`;
- chạy một lần sau daily cutoff và khi dữ liệu đủ;
- chỉ xử lý portfolio có `mode=auto` và explicit opt-in;
- acquire advisory lock theo portfolio + symbol + target;
- tạo decision/order idempotent;
- circuit breaker khi data/model/price/risk unavailable;
- container riêng `paper-trader`, không chạy trong API request.

## 11. Test plan

```text
tests/decision/trading/
  test_policy.py
  test_policy_store.py
  test_decision_service.py
  test_execution.py
  test_performance.py
  test_backtest.py

tests/app/test_paper_trading.py
tests/warehouse_agents/test_trade_decision.py
frontend/src/trading/*.test.jsx
```

Cases bắt buộc:

- q interval cắt zero → support giảm/NO_TRADE theo config;
- forecast stale/unavailable → NO_TRADE;
- BUY/SELL/HOLD/NO_TRADE đúng với portfolio state;
- SELL không tạo short;
- slippage/PnL chính xác và không có fee ẩn;
- double click/retry chỉ có một order/fill;
- hai user không đọc/execute portfolio của nhau;
- future data mutation không thay historical decision;
- backtest không leakage;
- API không tin browser price/quantity/user key;
- Trade Agent không gọi execution mutation;
- dashboard thể hiện unavailable/stale, không dựng số giả.

## 12. Rollout theo phase

### Phase 0 — Policy research

- migration + contracts;
- backtester và report;
- chọn threshold/risk config trên validation;
- checksum `daily_quantile_v1.json`.

Deliverable: report so baselines, chưa có UI execution.

### Phase 1 — Advisory

- `trade_decision` tool;
- Trade Agent giải thích BUY/SELL/HOLD/NO_TRADE;
- persist decision/evidence;
- không tạo order.

Deliverable: quyết định reproducible và audit được.

### Phase 2 — Manual paper trading

- portfolio/order/fill repository;
- preview + explicit confirm;
- accounting/PnL/risk;
- API user isolation.

Deliverable: paper fills idempotent, không có đường tới sàn thật.

### Phase 3 — Dashboard

- Paper Trade workspace;
- portfolio, current decision, positions, trades, equity curve, benchmark;
- freshness/version/risk display.

### Phase 4 — Optional auto-paper

- scheduler container;
- explicit opt-in và circuit breakers;
- theo dõi ít nhất một evaluation window trước khi cân nhắc thay rule.

## 13. Definition of done

- policy backtest test split và baselines được báo cáo đầy đủ;
- decision deterministic, versioned, causal và có evidence checksum;
- model unavailable không tạo order;
- no short/no leverage/no negative cash trong v1;
- retry không tạo duplicate fill;
- user isolation được integration-test bằng PostgreSQL;
- dashboard reconcile chính xác với database views;
- Trade Agent chỉ giải thích tool result;
- không có API key sàn hoặc network call đặt lệnh;
- docs ghi rõ paper simulation, không phải financial advice.

## 14. Các quyết định cần chốt trước Phase 0

Khuyến nghị mặc định:

| Quyết định | Khuyến nghị v1 |
|---|---|
| Trading mode | long-only spot |
| Asset | BTC, ETH |
| Starting cash | 100,000 USDT/user portfolio |
| Confirmation | manual explicit confirm |
| Forecast cadence | daily UTC |
| Decision refresh | một decision/target/asset/policy version |
| Execution source | latest fully closed 1m Binance candle |
| Fee | không mô phỏng trong v1 |
| Slippage | 5 bps, versioned trong policy config |
| Auto trading | tắt |
| Anonymous users | xem demo read-only, không lưu/execute |

Threshold, max allocation và slippage cuối cùng phải được chọn trong Phase 0,
không quyết định bằng cách nhìn kết quả test rồi tune ngược.
