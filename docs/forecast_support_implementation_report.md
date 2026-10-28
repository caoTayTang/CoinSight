# Daily forecast support — implementation report

Ngày hoàn thành: 23/10/2026.

## Kết quả

Public forecast đã chuyển sang `forecast_support`: dự báo giá đóng cửa UTC ngày kế
tiếp cho BTC hoặc ETH. Một response gồm q10/q50/q90, rolling backtest causal, thống
kê thị trường, trend nến giờ, độ mới/coverage/lineage và model version. Hourly
CatBoost cũ vẫn tồn tại đúng một đường A2A nội bộ để rollback, nhưng không còn được
MCP/agent graph công bố như public forecast.

Hai bundle đang pin độc lập:

| Symbol | Run ID | Bundle version | Input |
|---|---|---|---|
| BTC | `107b4799-4ae1-460e-8d3c-60182d073552` | `2026-10-23-direction-v1` | 90 ngày × 275 features |
| ETH | `2aee3ffb-3ffd-4508-9644-5a45cb145e23` | `2026-10-23-direction-v1` | 90 ngày × 275 features |

Cả hai là GRU `daily-return-v2`, horizon 1 ngày, có target scaler và ba quantile.
Bundle được lưu dưới `data/models/daily-forecast/` (thư mục model bị `.gitignore`).

## Luồng runtime

```text
forecast_support request
  → validate BTC/ETH và giới hạn N/K
  → load + verify checksum của bundle đã pin
  → tính exact daily/hourly ranges
  → audit DW (grid + duplicate + OHLCV validity + mọi context coin)
  → nếu đủ: không gọi downloader/staging
  → nếu thiếu: advisory lock → audit lại → archive/REST đúng gap
               → staging → DQ/UPSERT → audit lại
  → daily q10/q50/q90 inference
  → rolling causal evaluation + market statistics + hourly trend
  → response hữu hạn, bounded và có lineage
```

Nếu model, database, bundle hoặc dữ liệu không hợp lệ, service trả trạng thái
`unavailable`/`insufficient_data`; không sinh forecast giả và không fallback ETH sang
BTC.

## File mới

| File | Mục đích |
|---|---|
| `pipeline/decision/serving/contracts.py` | Request/readiness/sync contracts và public bounds |
| `pipeline/decision/serving/model_bundle.py` | Build, pin, checksum-first load và validate bundle |
| `pipeline/decision/serving/data_readiness.py` | Tính range, audit-before-sync, re-audit và concurrency flow |
| `pipeline/decision/serving/targeted_sync.py` | Binance archive + REST-tail repair, advisory lock, staging/UPSERT |
| `pipeline/decision/serving/daily_forecast_service.py` | Multi-asset daily inference và q10/q50/q90 price conversion |
| `pipeline/decision/serving/rolling_evaluation.py` | Frozen batched causal backtest trên N ngày đã realized |
| `pipeline/decision/serving/market_statistics.py` | Daily aggregates và K-hour log-price regression |
| `pipeline/decision/serving/support_service.py` | Orchestrator và fail-closed public response |
| `pipeline/decision/serving/cli.py` | CLI build bundle/report |
| `tests/decision/forecasting/test_forecast_serving.py` | Contract, readiness, repair, statistics và checksum tests |

## File đã sửa

- `pipeline/batch/staging_writer.py`: stage bounded Binance REST records với batch và
  source-file lineage giống archive.
- `agents/prediction.py`, `agents/server.py`, `agents/gateway.py`: nối daily support
  vào A2A/MCP; giữ hourly route cũ chỉ để rollback.
- `warehouse_agents/tools.py`, `graph.py`, `action_contracts.py`, `desk.py`: public
  allowlist/schema/routing `/predict BTC|ETH` dùng `forecast_support`.
- `warehouse_agents/skills/forecast-explainer/SKILL.md` và `market-brief/SKILL.md`:
  cách diễn giải daily quantile, empirical coverage và retrospective metrics.
- `frontend/src/responsePolicy.js`: chart reference/q10/q50/q90 cho daily forecast.
- `agents/Dockerfile`, `agents/requirements.txt`, `compose.agents.yml`: thêm runtime
  PyTorch CPU, pipeline modules, DB/raw/model mounts.
- `Makefile`: thêm `forecast-bundle` và `forecast-support`.
- `scripts/check_local_agents.py`: smoke contract mới.
- `tests/agents/test_a2a.py`, `test_mcp.py`,
  `tests/warehouse_agents/test_desk.py`: contract tests mới.

## Cách đóng gói model

Một tested run chỉ được activate sau khi toàn bộ artifact reload thành công:

```bash
make forecast-bundle \
  RUN_DIR=data/forecasting/runs/BTC/gru/<run-id> \
  VERSION=2026-10-23-direction-v1
```

Chạy lại tương tự cho ETH. `active.json` chỉ được thay atomically sau verify.

## Cách chạy trực tiếp

PostgreSQL phải chạy và chứa schema DW/meta/staging hiện tại:

```bash
make forecast-support SYMBOL=BTC
make forecast-support SYMBOL=ETH PERFORMANCE_DAYS=60 MARKET_DAYS=30 TREND_HOURS=336
```

Cutoff lịch sử tùy chọn:

```bash
make forecast-support SYMBOL=BTC CUTOFF=2026-10-20T12:00:00Z
```

Service tự tính range; không có argument cho user/LLM chọn `backfill_start`.

## Cách chạy qua agent

```bash
make agents-up
make agents-smoke
```

Public MCP tool:

```text
forecast_support(symbol, performance_days, market_days, trend_hours, cutoff)
```

Lưu ý: tool có `readOnlyHint=false`, vì khi audit phát hiện gap nó được phép stage và
UPSERT đúng dependency range. Nếu warehouse đã đủ, test/invariant bảo đảm không gọi
sync.

## Kiểm chứng đã chạy

- `159 passed` cho toàn bộ `tests/decision`.
- Bundle BTC và ETH reload qua checksum; đều có 275 features đúng thứ tự.
- Offline tensor smoke trên sample thật cho cả BTC/ETH tạo quantile hữu hạn và
  `q10 <= q50 <= q90`.
- PostgreSQL/Docker end-to-end chưa chạy được trong sandbox hiện tại vì Docker socket
  không được cấp quyền và localhost DB không truy cập được. Service đã trả
  `status=unavailable` thay vì tạo kết quả giả.
- Agent dependency tests chưa chạy trong sandbox vì network bị chặn và môi trường
  hiện tại không có A2A/MCP packages; Python compile đã qua. Chạy `make agents-test`
  sau khi build runtime trên máy host.

## Giới hạn có chủ ý

- Recent performance là causal retrospective diagnostic, không khẳng định là unseen
  prospective test.
- q10–q90 là empirical model interval, không được gọi là “80% chắc chắn”.
- MAE và direction accuracy có thể đưa ra kết luận khác nhau; response giữ cả hai.
- Agent paper-trading chưa nằm trong thay đổi này; đây mới là support tool làm nền cho
  agent đó.
