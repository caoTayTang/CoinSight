# Đọc code theo một request

Đừng đọc toàn repo từ đầu. Chọn một luồng dưới đây, mở file theo thứ tự và đối chiếu [contract](agent_contracts.md). **Model ML tính số; agent LLM chọn tool và giải thích; router chỉ chọn provider/model LLM.**

## 1. Bản đồ thư mục

| Thư mục | Vai trò | Bắt đầu đọc khi… |
| --- | --- | --- |
| `frontend/src/` | Market, Operations, Desk chat, docs | Muốn biết người dùng bấm gì và API nào được gọi |
| `app/` | FastAPI, SQL đọc warehouse, Desk chat cũ | Muốn hiểu dữ liệu lên web và contract API |
| `pipeline/batch/` | Tải archive, staging, quality, warehouse loader | Muốn hiểu dữ liệu lịch sử vào kho |
| `pipeline/stream/` | Producer và Spark xử lý nến trực tiếp | Muốn hiểu dữ liệu live |
| `postgres/init/`, `postgres/migrations/` | Schema, fact/dimension, views/marts, lineage | Muốn hiểu grain, khóa và kiểm dữ liệu |
| `pipeline/decision/` | Feature, train/evaluation/research ML | Muốn hiểu cách train model và thí nghiệm |
| `agents/` | Tool dự báo cố định + MAD qua MCP/A2A | Muốn trace một forecast, không có LLM planner |
| `warehouse_agents/` | Isolation Forest, hai reasoning agent, router, tools | Muốn trace Analyst/Ops hoặc đổi provider |
| `tests/agents/`, `tests/warehouse_agents/` | Ví dụ chạy được và trường hợp bị từ chối | Muốn biết hệ thống thực sự cam kết điều gì |
| `data/models/` | Model, snapshot và proof local; thường ignored | Muốn đối chiếu artifact, không phải mã ứng dụng |

## 2. Đọc luồng web trước — khoảng 10 phút

1. `frontend/src/main.jsx`: `/docs/` mở DocsApp; đường khác mở ứng dụng.
2. `frontend/src/App.jsx`: navigation và workspace Market/Operations.
3. `frontend/src/components.jsx`, hàm submit của Desk chat: gửi tới **`/v1/agent/command`** (plain text thành lệnh `trade`).
4. `app/api.py` → `app/desk_commands.py`: proxy cùng origin tới extension.
5. `warehouse_agents/desk.py` → Analyst (`warehouse_agents/graph.py`): vòng LangGraph + tool, router chọn model.

**Một nhánh Desk:** plain text, `@trade`/`@sre` và `/tool` được parse tại `frontend/src/deskCommands.js` → `/v1/agent/command` → `app/desk_commands.py` → `warehouse_agents/desk.py`. Trade tương ứng `analyst`, SRE tương ứng `operations` trong code. [Cú pháp và contract lệnh](desk_commands.md).

## 3. Đọc một forecast — khoảng 15 phút

```text
agents/gateway.py: forecast_support
  → agents/rpc.py: call_agent
  → agents/server.py: Executor.execute (prediction)
      → pipeline/decision/serving/support_service.py
      → audit DW; targeted sync chỉ khi thiếu
      → load bundle BTC/ETH riêng, daily quantile inference
      → rolling evaluation + market/hourly aggregates
      → structured artifact + task completed
```

Mở từng file và chú ý:

- `ForecastSupportRequest`: allowlist BTC/ETH và giới hạn N/K.
- `ForecastModelBundle`: checksum, feature order, scaler và input size.
- `load_context`: lấy BTC + ETH cùng cutoff; nguồn lỗi/thiếu thì không đoán bù.
- `frozen_models`: kiểm checksum/spec trước khi nạp hai member đã duyệt. Serving không train mới.
- `predict`: dựng bộ feature `compact` và bộ có ETH; kiểm thứ tự cột; tổ hợp theo hệ số đã khóa; đổi log return sang predicted close bằng `reference * exp(return)`.
- `generated_at`, `target_open`, `target_close`, `target_already_started`: cho biết dự báo được tạo lúc nào so với giờ mục tiêu.

Muốn hiểu daily quantile feature và policy đang phục vụ, đọc
[Daily quantile trading policy](trading_policy_guide.md). Các file
`pipeline/decision/hourly_engineering.py` và `hourly_cross_asset.py` thuộc nhánh
hourly legacy/research; không dùng chúng để suy ra logic daily policy hiện tại.

Muốn hiểu export: `scripts/prepare_agent_bundle.py`. Bundle local: `data/models/agent-serving-bundle/v1/`.

### Đọc Paper Trade policy

```text
forecast_support
  → DailyQuantilePolicy.evaluate
  → target position fraction
  → BUY / SELL / HOLD / NO_TRADE
  → frozen paper.decision
  → preview bằng closed-minute price
  → explicit confirmation
  → immutable paper order + fill
```

Đọc lần lượt `pipeline/decision/trading/contracts.py`, `policy.py`,
`decision_service.py`, `repository.py`, rồi mới tới `historical_backtest.py` và
`backtest.py`. Công thức, statistics, config và khái niệm portfolio được giải
thích chi tiết trong [trading policy guide](trading_policy_guide.md).

## 4. Đọc anomaly thử nghiệm (đã tắt trong production)

Các file sau được giữ để nghiên cứu. `market_anomaly` không còn được đăng ký ở MCP/Desk/Analyst graph.

**MAD cố định:** `agents/domain.py` → `detect_anomalies`. So nến vừa đóng với các nến trước bằng median/MAD của return, volume và range. Ngưỡng robust-z là 6. Không có bước train classifier.

**Isolation Forest BTC/ETH hourly + daily đã train:**

```text
warehouse_agents/gateway.py: market_anomaly (decorator đã comment)
  → warehouse_agents/tools.py: detect_market_anomaly
      → warehouse_agents/market.py: closed_candles (hai frequency)
      → pipeline/decision/anomaly/bundle.py: load → checksum → score
      → pipeline/decision/anomaly/features.py: causal hourly/daily features
      → trả hai score/threshold/flag; chưa có trading strategy
```

Đọc `features.py` trước, rồi `bundle.py`, `training.py`, `cli.py`. Reference rolling luôn shift một period nên candle đang chấm không tự làm thay đổi baseline. Model không học nhãn normal/anomaly; score lớn nghĩa là khác thường hơn. Flag khi score >= threshold calibration đã khóa.

Muốn hiểu training: `pipeline/decision/anomaly/training.py` → `train_bundle()`. Đọc temporal train/calibration/test, quantile threshold, evaluation rồi artifact `data/models/market-anomaly/<symbol>/<frequency>/<version>/`. `warehouse_agents/anomaly.py` và `train_anomaly.py` là đường legacy dành cho model-health compatibility, không phải tool anomaly public mới.

## 5. Đọc agent LLM và routing — khoảng 15 phút

1. `warehouse_agents/gateway.py`: ba tool MCP public (`load_skill`, `ask_analyst`, `ask_operations`); `model_health` được giữ offline nhưng không advertise.
2. `warehouse_agents/server.py`: request `{question, symbol}`, tạo task A2A, kiểm input, admission/concurrency và trả artifact.
3. `warehouse_agents/graph.py`: `Reasoner`, `SPECS`, `ANALYST`, `OPS`.
4. `Reasoner.reason()`: gửi hội thoại và tool schema cho router; LLM trả text hoặc tool call.
5. `Reasoner.execute_tools()`: kiểm tên tool/schema rồi mới gọi hàm thật; tool output quay lại graph.
6. `warehouse_agents/router.py`: `Router.converse()` → chọn route; `invoke()` gọi provider; `chat_request()`/`chat_response()` chuyển format để giữ tool-call ID khi đổi provider.
7. `warehouse_agents/router.json`: cấu hình vòng xoay; đây là chỗ đổi model/key reference, không phải feature ML.
8. `warehouse_agents/tools.py`: nơi SQL/HTTP/A2A thực sự xảy ra. LLM không được tự chạy SQL hay shell.

Trong graph, tìm `START`, `reason`, `tools`, `END`: đó là vòng suy luận. Tìm `investigate_warehouse` để thấy Analyst gọi Operations qua A2A. Hai model CatBoost tự chúng không có vòng suy luận này.

## 6. Đọc contract và test trước khi sửa

| Muốn sửa | Đọc contract / test |
| --- | --- |
| Candle, cutoff, forecast | `agents/domain.py`, `tests/agents/`, [contract forecast/anomaly](agent_contracts.md) |
| Feature causal / anomaly artifact | `tests/warehouse_agents/test_intelligence.py`, `test_market.py` |
| Tool quyền hạn / graph | `test_intelligence.py`, `test_a2a.py` |
| Provider/model/key và round-robin | `test_router.py` |
| Auth, request limit, TTL | `test_runtime.py` |
| SQL coverage / reconciliation / mart | `test_postgres.py`; cần DB test tách biệt |
| Docs navigation và link | `frontend/src/docs-navigation.test.js` |

Để tìm nhanh:

```sh
rg -n 'class CandleContext|def predict|def detect_anomalies' agents
rg -n 'class Reasoner|def reason|def execute_tools|investigate_warehouse' warehouse_agents
rg -n 'class Router|def converse|round_robin' warehouse_agents/router.py
rg -n 'warehouse_coverage|warehouse_mart_parity|def query' warehouse_agents/tools.py
```

## 7. Thứ tự đọc tối thiểu

Nếu chỉ có 30 phút: **trang này → `pipeline/decision/anomaly/features.py` → `bundle.py` → `warehouse_agents/tools.py` → `warehouse_agents/graph.py` → `warehouse_agents/router.json`**.

Sau đó đọc [Contract model, tool và agent](agent_contracts.md). Chỉ mở các file train/research khi cần thay mô hình; không chỉnh chúng để đổi model LLM.


## SRE retrieval và fine-tune

Xem [SRE retrieval, drift và fine-tune](sre_rag.md) để đọc pipeline, nguồn kiến thức, các phép kiểm và phần chưa được triển khai.
