# Paper trading implementation report

Giải thích đầy đủ forecast quantile, support statistics, portfolio, signed score,
risk penalty, allocation và backtest nằm tại
[Daily quantile trading policy](trading_policy_guide.md).

Ngày hoàn tất: 2026-10-27  
Scope: BTC/ETH, daily forecast support, long-only spot, manual paper execution.

## 1. Kết quả

Flow đã được triển khai:

```text
forecast_support (BTC/ETH)
        ↓ frozen evidence
DailyQuantilePolicy (deterministic)
        ↓ BUY / SELL / HOLD / NO_TRADE
paper.decision
        ↓ preview bằng latest closed 1m price
explicit user confirmation
        ↓
paper.paper_order + paper.fill + paper.equity_snapshot
        ↓
Paper Trade dashboard
```

Hai ranh giới quan trọng:

- `trade_decision` của Trade Agent chỉ advisory và luôn trả `executable=false` ở
  lớp tool; nó không thể tạo order/fill.
- chỉ authenticated Paper API sau bước preview và confirm mới ghi paper fill.

Không có Binance order API, exchange credential, short, leverage hoặc auto scheduler.
Theo quyết định hiện tại, hệ thống **không mô phỏng trading fee**. Fill chỉ áp dụng
slippage 5 bps được version hóa trong policy.

## 2. Rule quyết định

Config nằm tại
`pipeline/decision/trading/policies/daily_quantile_v1.json`, có checksum SHA-256
được lưu cùng decision. Đây là heuristic `v1-research`, paper-only, chưa phải policy
được chứng minh đủ tốt cho tiền thật.

### 2.1. Input

- q10/q50/q90 return của next UTC daily close;
- directional accuracy, sample count và relative MAE trong rolling window;
- daily realized/annualized volatility, cumulative return, up-day ratio, drawdown;
- regression direction và R² của closed-hour trend;
- cash, equity, current BTC/ETH position và portfolio drawdown;
- latest fully closed 1-minute market price.

### 2.2. Score

Các component đều được giới hạn trong `[-1, 1]`:

```text
signed_score = clip(
    0.30 × median_direction
  + 0.25 × interval_position
  + 0.20 × direction_reliability
  + 0.15 × trend_alignment
  + 0.07 × momentum
  + 0.03 × up_day_balance
)
```

- q10 và q90 cùng dương/âm cho interval evidence mạnh hơn;
- interval cắt zero thêm risk flag;
- relative MAE ≥ 1 giảm signed score 15% nhưng không đảo hướng;
- volatility/drawdown thị trường vượt gate giảm score;
- portfolio drawdown ≤ -25% đặt target position về 0;
- `abs(score) < 0.25` giữ vị thế (`HOLD`);
- score dương đủ mạnh tạo target long, tối đa 35% equity;
- mỗi order tối đa 15% equity;
- score âm đủ mạnh chỉ giảm/đóng long, không được mở short;
- rebalance delta ≤ 2% equity tạo `HOLD`.

`support_score = abs(signed_score)` chỉ là deterministic support score, không phải
xác suất thắng.

### 2.3. Gate tạo `NO_TRADE`

- forecast support/data grid unavailable;
- q10 ≤ q50 ≤ q90 không đúng;
- target close đã qua;
- execution price cũ hơn 300 giây;
- recent performance có ít hơn 14 samples;
- paper cash/position không đủ cho action.

## 3. File mới

### Domain và policy

| File | Mục đích | Method/class chính và logic |
|---|---|---|
| `pipeline/decision/trading/__init__.py` | Public exports của package | export policy store, policy và causal backtester |
| `pipeline/decision/trading/contracts.py` | Contract dependency-light giữa policy/repository/API | `PortfolioState` đóng băng trạng thái trước decision; `DecisionDraft` chứa action/score/reasons; `OrderPreview` chứa exact simulated fill trước confirm |
| `pipeline/decision/trading/policy_store.py` | Load/validate policy version | `PolicyStore.load()` chỉ chấp nhận tên an toàn, kiểm required keys/range, tính SHA-256 và cache config |
| `pipeline/decision/trading/policy.py` | Pure decision function, không I/O | `DailyQuantilePolicy.evaluate()` chạy readiness/freshness gate, tính sáu signal components, risk penalty, target position và BUY/SELL/HOLD/NO_TRADE |
| `pipeline/decision/trading/decision_service.py` | Orchestration boundary | `evaluate()` đọc portfolio state rồi chạy policy; `create()` persist evidence; `preview()`/`execute()` lấy slippage từ policy config |
| `pipeline/decision/trading/repository.py` | PostgreSQL, accounting và atomic paper execution | xem chi tiết bên dưới |
| `pipeline/decision/trading/backtest.py` | Replay policy trên causal evidence đã được tạo sẵn | `PolicyBacktester.run()` sort observation theo thời gian, mark-to-market, evaluate, mô phỏng slippage, trả trades/equity/max drawdown/buy-hold return |
| `pipeline/decision/trading/report.py` | Xuất artifact backtest portable | `PolicyBacktestReport.write()` ghi summary JSON, equity CSV và trades CSV |
| `pipeline/decision/trading/policies/daily_quantile_v1.json` | Single source of truth của threshold/risk/slippage | `v1-research`, long-only, paper-only, no fee |

Các method chính của `PaperTradingRepository`:

- `create_portfolio()`/`list_portfolios()`/`portfolio()`: user-scoped portfolio và
  summary được mark bằng latest closed minute price.
- `state()`: replay fills để tạo `PortfolioState` đúng tại lúc evaluate.
- `save_decision()`: ghi model/policy version, action, evidence JSON và evidence hash;
  unique theo portfolio/symbol/target/policy/model.
- `preview()`: tính BUY/SELL fill từ market price và slippage, nhưng không mutation.
- `execute()`: lock portfolio row, kiểm idempotency, kiểm decision chưa hết hạn,
  enforce cash/long-only, rồi ghi order + fill + equity snapshot trong một transaction.
- `_replay()`: tái tạo cash, quantity, weighted-average entry và realized PnL từ
  immutable fills; không tin số dư do browser gửi lên.
- `_latest_prices()`: chỉ đọc `dw.fact_candle_minute_live` đã đóng, không dùng
  predicted close làm execution price.

### Database và API

| File | Mục đích |
|---|---|
| `postgres/migrations/012_paper_trading.sql` | Tạo schema `paper`, 5 tables và `paper.trade_history`; không có fee column |
| `app/paper_trading.py` | Authenticated REST API cho portfolio/decision/preview/confirm/orders/equity |
| `app/Dockerfile.dockerignore` | Cho API root-context build chỉ gửi `app/` và `pipeline/`, không gửi data/repo thừa |

Database tables:

- `paper.portfolio`: owner, initial cash, mode/status/version;
- `paper.decision`: immutable-ish policy result + full frozen evidence;
- `paper.paper_order`: side/notional/idempotency/status;
- `paper.fill`: market/fill price, quantity, slippage, balances sau fill;
- `paper.equity_snapshot`: equity/PnL/drawdown audit points.

REST endpoints:

```text
POST /v1/paper/portfolios
GET  /v1/paper/portfolios
GET  /v1/paper/portfolios/{portfolio_id}
POST /v1/paper/portfolios/{portfolio_id}/decisions
GET  /v1/paper/portfolios/{portfolio_id}/decisions/latest?symbol=BTC
POST /v1/paper/portfolios/{portfolio_id}/orders/preview
POST /v1/paper/portfolios/{portfolio_id}/orders
GET  /v1/paper/portfolios/{portfolio_id}/orders
GET  /v1/paper/portfolios/{portfolio_id}/equity
```

### Trade Agent

| File | Thay đổi |
|---|---|
| `warehouse_agents/tools.py` | thêm `trade_decision()`; lấy identity từ `CURRENT_USER`, gọi `forecast_support`, evaluate policy và ép response thành advisory-only |
| `warehouse_agents/action_contracts.py` | schema strict cho BTC/ETH, UUID portfolio và bounded windows |
| `warehouse_agents/graph.py` | advertise/map `trade_decision` cho Analyst/Trade Agent; prompt cấm tool tạo order |
| `warehouse_agents/skills/market-brief/SKILL.md` | hướng dẫn chỉ dùng BUY/SELL/HOLD khi trích policy result và chỉ rõ confirm ở dashboard |
| `warehouse_agents/Dockerfile` | copy shared `pipeline/` hiện tại để agent không vô tình dùng decision code cũ từ base image |

Identity không xuất hiện trong tool schema nên LLM không thể chọn `user_key` của
người khác. Nếu user có nhiều portfolio, tool yêu cầu `portfolio_id`; nếu chỉ có
một portfolio, nó tự chọn portfolio đó. Tool không gọi `save_decision()` hay
`execute()`.
Tool đổi eligibility nội bộ thành `paper_order_eligible` nhưng ép cả top-level và
`decision.executable` về `false`, tránh để LLM hiểu nhầm rằng nó được phép execute.

### Frontend

| File | Mục đích |
|---|---|
| `frontend/src/trading/tradingApi.js` | JSON REST wrapper, decision tone và pure SVG equity path helper |
| `frontend/src/trading/TradingDashboard.jsx` | workspace Paper Trade: create/select portfolio, BTC/ETH decision, quantiles, preview/confirm, positions, PnL, drawdown, equity và fill history |
| `frontend/src/tradingApi.test.js` | unit test helper/curve edge cases |

Confirm modal cho thấy quantity, market price, fill price, notional, candle time và
slippage; đồng thời ghi rõ không có fee và không gửi lệnh ra sàn.

## 4. File đã sửa

- `app/api.py`: mount paper router.
- `app/Dockerfile`: dùng root context để copy shared decision package.
- `docker-compose.yml`: đổi API build context tương ứng.
- `frontend/src/App.jsx`: thêm lazy workspace `Paper Trade`, chỉ hiện với user không
  anonymous; local development vẫn dùng identity `local`.
- `frontend/styles.css`: responsive layout cho paper dashboard/modal/table/chart.
- `warehouse_agents/Dockerfile.dockerignore`: cho warehouse-agent root-context
  build nhận `warehouse_agents/` và shared `pipeline/`.
- `agents/Dockerfile.dockerignore`: cho local prediction-agent root-context build
  nhận đầy đủ `agents/` và shared `pipeline/` phục vụ daily model.
- `docs/paper_trading_implementation_plan.md`: bỏ fee khỏi scope/formula/schema/test,
  đồng bộ config và file layout thực tế.
- `compose.agents.yml`: giữ anomaly implementation dưới profile experimental để
  default stack không khởi động nó.

## 5. Safety và consistency

- Browser không gửi price, quantity, user key hoặc target allocation.
- Server luôn resolve owner từ auth dependency.
- UUID portfolio luôn được query cùng `user_key`.
- Preview không ghi DB; confirm mới mutation.
- Confirm phải gửi lại `source_candle_time` của preview; nếu latest closed candle đã
  đổi, server bắt preview lại thay vì fill ở mức giá user chưa nhìn thấy.
- `idempotency_key` và unique constraints chống retry/double click.
- Portfolio row lock chống hai confirmation chạy đồng thời.
- Không negative cash, negative position, short hoặc leverage.
- Decision hết `valid_until` và stale minute price đều bị reject.
- Evidence/model/policy version và SHA-256 được lưu để audit/reproduce.
- Không có đường code nào kết nối exchange trading endpoint.

## 6. Tests

File test mới:

- `tests/decision/trading/test_policy.py`: bullish BUY, bearish exit, stale/incomplete
  gates, MAE penalty, no-fee config.
- `tests/decision/trading/test_backtest.py`: causal replay BUY→SELL, turnover và
  explicit `fee_simulation=false`.
- `tests/app/test_paper_trading.py`: raw forecast evidence và server-owned
  user/portfolio/idempotency arguments.
- `tests/warehouse_agents/test_trade_decision.py`: identity từ context và advisory-only.
- `frontend/src/tradingApi.test.js`: action tone và finite SVG path.

Kết quả đã chạy trong workspace:

```text
.venv/bin/python -m pytest -q tests/decision/trading
6 passed

.venv/bin/python -m py_compile ...
passed

node frontend/src/tradingApi.test.js
2 passed

git diff --check
passed

docker compose config --quiet
passed
```

Các integration suite app/agent chưa chạy được trong `.venv` hiện tại vì environment
đang thiếu `PyJWT` và `a2a-sdk`. Full frontend build cũng chưa chạy được vì sandbox
không resolve npm registry sau khi `node_modules` cũ vốn đã thiếu Vite. Docker daemon
trong phiên này bị từ chối quyền, nên migration chưa được apply/test trực tiếp ở DB.
Đây là verification còn lại, không được ghi nhận giả là đã pass.

## 7. Cách deploy/test trên máy

```bash
# 1. Apply additive migration
docker compose run --rm migrate

# 2. API + frontend cần rebuild vì source được COPY vào image
docker compose build api frontend
docker compose up -d api frontend

# 3. Rebuild Trade/Operations/MCP image vì tool và shared policy đổi
docker compose -p coinsight-warehouse-agents \
  -f warehouse_agents/compose.yml build
docker compose -p coinsight-warehouse-agents \
  -f warehouse_agents/compose.yml up -d

# 4. Recreate local-agent stack; anomaly profile mặc định không chạy
docker compose -p coinsight-agents -f compose.agents.yml up -d --remove-orphans
# Nếu container anomaly từ lần chạy cũ vẫn còn:
docker compose -p coinsight-agents -f compose.agents.yml \
  --profile experimental-anomaly rm -sf anomaly-agent

# 5. Verify
docker compose ps
curl -fsS http://127.0.0.1:8000/openapi.json >/dev/null
```

Sau đó mở `http://127.0.0.1:3000`, chọn `Paper Trade`, tạo portfolio, chọn BTC/ETH,
bấm `Evaluate now`, xem evidence, `Preview paper order`, rồi mới confirm.

## 8. Giới hạn còn lại

- Rule threshold hiện là heuristic; backtester đã có nhưng chưa có job sinh toàn bộ
  historical frozen `forecast_support` observations và chưa có validation report.
- Equity snapshot hiện được ghi khi có fill; chưa có scheduled mark-to-market snapshot.
- Không có fee theo scope hiện tại nên simulated return sẽ cao hơn môi trường có fee.
- No auto-paper scheduler; mỗi fill cần user confirm.
- Chỉ BTC/ETH và long-only.
- Dashboard chưa có benchmark curve trên cùng biểu đồ; backtest result có
  `buy_hold_return` để bổ sung sau.

Vì vậy hệ thống phù hợp để thử nghiệm/audit integration, chưa đủ bằng chứng để dùng
policy này cho tiền thật.
