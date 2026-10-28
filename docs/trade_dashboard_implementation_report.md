# Trade Agent dashboard implementation report

Để đọc logic model/support/policy theo hướng nhập môn, xem
[Daily quantile trading policy](trading_policy_guide.md). Report này tập trung vào
những file và chức năng đã triển khai; guide kia giải thích công thức và khái niệm.

## Outcome

The existing authenticated **Paper Trade** workspace now covers the complete
research loop:

1. inspect and edit the daily quantile policy;
2. validate and save a user-scoped policy override;
3. run a causal backtest of the unsaved draft on the active model bundle's
   frozen test split, with a selectable UTC range locked at `2026-02-01` or
   later;
4. inspect return, P&L, drawdown, buy-and-hold comparison, action utility,
   hold reasons and the equity curve;
5. explicitly ask Trade Agent to explain the compact backtest summary;
6. inspect the latest daily candlesticks with q10/q50/q90 next-close forecast;
7. preview and explicitly accept paper orders;
8. inspect portfolio P&L and next-day useful/harmful attribution per accepted
   fill.

The backtest equity chart uses one shared USDT domain for both series: the
solid blue line is policy equity (cash plus marked-to-market position), while
the dashed gray line is buy-and-hold equity. Agent explanations are rendered
as sanitized GitHub-flavoured Markdown, including tables and lists. The
forecast-direction card reads `forecast_direction_diagnostics.directional_accuracy`
and labels the metric explicitly as the sign accuracy of q50.

Each backtest equity row also freezes q10/q50/q90 and the realized next-day
return. The dashboard plots q50 against the realized return around a shared
zero line and marks the corresponding BUY, SELL or HOLD action. This chart is
the forecast diagnostic; unlike the cumulative equity chart, it exposes each
individual direction error.

Live order eligibility deliberately uses the latest closed one-minute candle
from `dw.fact_candle_minute_live`. Daily/hourly model backfill does not populate
that table: its independent path is Binance WebSocket → Kafka → Spark →
PostgreSQL. A stale minute stream therefore produces `execution_price_stale`
and blocks preview/fill rather than simulating against an old market price.

Migration `014_repeatable_paper_evaluation.sql` makes every **Evaluate now**
click a separate audit record. The earlier uniqueness constraint could return
the first decision for the same target/model/policy even after the minute price
became fresh. Each new decision now stores `evaluated_at`, execution price,
minute-candle close time, their age in seconds, and current allocation. The UI
shows those fields plus the signed score and bullish/bearish bias; this makes a
real clock/freshness mismatch distinguishable from an old frozen decision.

This remains a paper-only, long-only simulator. It has no exchange connection
and no fee model. Configured slippage is simulated.

## Policy isolation and auditability

The browser does **not** overwrite
`pipeline/decision/trading/policies/daily_quantile_v1.json`. A validated override
is stored in `paper.user_policy` by `user_key`.

`PolicyStore.normalize_user_config()`:

- copies only editable fields;
- fixes `policy_id=daily-quantile`, `mode=long_only_spot`, and
  `deployment_tier=paper-only`;
- validates all ranges;
- derives `version=v1-user-<digest>`;
- calculates a canonical SHA-256 checksum.

Every new `paper.decision` stores the exact policy in `policy_config`. Preview
and confirmation therefore use the frozen decision's slippage and maximum
price age even if the user changes their active config later.

## Main files

### New files

| File | Purpose | Main logic |
|---|---|---|
| `postgres/migrations/013_paper_policy_dashboard.sql` | Database upgrade | Adds `paper.user_policy` and frozen `paper.decision.policy_config`. |
| `agents/backtest_api.py` | Prediction-service backtest jobs | Validates a request, runs `HistoricalPolicyBacktestRunner` in a worker thread, exposes progress/result from an in-memory job registry. |
| `frontend/src/trading/ForecastCandleChart.jsx` | Forecast chart | Draws 60 daily OHLC candles in SVG and overlays reference→q50 plus the q10–q90 target interval. |
| `frontend/src/trading/PolicyWorkbench.jsx` | Policy/backtest UI | Renders documented config controls, progress, report cards, equity/buy-hold curves, action utility and agent explanation. |
| `frontend/src/trading/TradeAnalytics.jsx` | Accepted-order analytics UI | Shows portfolio P&L, useful/harmful totals and outcome per accepted fill. |
| `tests/decision/trading/test_dashboard_support.py` | Deterministic tests | Covers user-policy normalization and BUY/SELL usefulness aggregation. |

### Updated files

| File | Purpose of change |
|---|---|
| `pipeline/decision/trading/policy_store.py` | Added dict validation and safe user-policy normalization/versioning. |
| `pipeline/decision/trading/repository.py` | Added user-policy persistence, frozen policy evidence, daily candle query and accepted-order analytics. |
| `pipeline/decision/trading/decision_service.py` | Uses the user's active policy for new decisions and the decision's frozen policy for preview/execute. |
| `app/paper_trading.py` | Added policy, backtest proxy, candle and analytics endpoints plus field explanations. |
| `agents/server.py` | Registers prediction-agent backtest job routes. |
| `compose.agents.yml` | Mounts snapshot data and exposes the internal token/root required by backtesting. |
| `docker-compose.yml` | Gives the API the prediction-agent internal URL. |
| `frontend/src/trading/TradingDashboard.jsx` | Integrates the workbench, polling, agent explanation, forecast chart and analytics. |
| `frontend/src/trading/tradingApi.js` | Adds authenticated Trade Agent command helper. |
| `frontend/styles.css` | Responsive styles for policy controls, reports and SVG charts. |

## Accepted-order metric semantics

For a fill with quantity `q`, simulated fill `F`, and realized next-day target
close `T`:

```text
BUY effect  = q × (T - F)
SELL effect = q × (F - T)
```

Positive means the accepted action helped over the forecast horizon. For SELL,
this is **avoided loss / missed gain**, not short-sale profit. The dashboard
keeps this diagnostic separate from actual portfolio realized/unrealized P&L.

## Backtest execution

Backtests run in the prediction-agent container because that image has PyTorch,
the active model bundles, snapshots and forecasting dependencies. The web API
only validates ownership and proxies job creation/status. The browser polls a
job every two seconds, so a long replay does not hold one HTTP request open.

The prediction-agent also joins `coinsight_crypto-network`. The API calls
`http://prediction-agent:8000` and the runner calls PostgreSQL at
`postgres:5432`; neither connection relies on a host port bound only to
`127.0.0.1`.

The range uses an inclusive `start` and exclusive `end`. Both the public API
and prediction-agent reject dates before `2026-02-01`, so the restriction
cannot be bypassed by changing the HTML. Leaving `end` empty uses the start of
the current UTC day, which means the final scored target is the latest fully
closed daily candle.

Before prefetch/replay, the runner audits the union of every required daily and
hourly model window. `TargetedBackfillService` repairs only missing ranges,
audits again, and aborts rather than inventing candles if coverage is still
incomplete. The report includes both `data_readiness_before_backfill` and final
`data_readiness` evidence.

The current job registry is intentionally process-local. Restarting the
prediction-agent cancels/forgets running reports; completed results should be
persisted in PostgreSQL only if durable research history becomes a requirement.

## Deploy locally

Apply the idempotent migration and rebuild only the changed services:

```bash
docker compose up -d postgres migrate
docker compose -p coinsight-agents -f compose.agents.yml up -d --build prediction-agent
docker compose up -d --build api frontend
```

Then open `http://127.0.0.1:3000`, sign in, and select **Paper Trade**.

The default backtest period is the active bundle's frozen test split. BTC and
ETH each require a valid active bundle plus its referenced snapshot manifest.

## Verification

Completed locally:

```text
python3 -m compileall ...                         passed
.venv/bin/python -m pytest tests/decision/trading -q
12 passed
node --test frontend/src/tradingApi.test.js
1 passed
```

The full frontend test/build could not run from the host because the existing
`frontend/node_modules` is incomplete (`vite`, `unified`, `jsdom`, and
`github-slugger` are missing). The Docker frontend build runs `npm ci` from the
lockfile and is the intended clean build path. This Codex sandbox could not
connect to the host Docker daemon, so the image build must be run by the local
developer account with the deploy commands above.
