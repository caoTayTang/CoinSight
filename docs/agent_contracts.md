# Contract model, tool và agent

Contract là điều kiện input được chấp nhận, ý nghĩa output và cách báo lỗi. Đọc nó trước khi nối UI hoặc đổi feature. Nguồn chính là schema/validator và test, không phải tên service.

## 1. Contract nến và thời gian

Nguồn: `agents/domain.py`, `agents/market.py`, `warehouse_agents/market.py`.

Một nến có `open_time`, `open_price`, `high_price`, `low_price`, `close_price`, `volume_quote`, `trade_count`. Giá phải dương và hữu hạn; volume/trades không âm; OHLC phải nằm trong biên hợp lệ. Timestamp có timezone, đúng mốc giờ và được chuẩn hóa UTC.

`CandleContext` dùng đúng **169 nến liên tục trước cutoff**, thứ tự tăng. Không chấp nhận giờ tương lai hoặc nến chưa đóng. Cutoff là ranh giới kết thúc cửa sổ dữ liệu, không phải thời điểm request đến server.

Ví dụ minh họa: cutoff `2026-10-19T13:00:00Z` dùng nến mở từ 169 giờ trước tới `12:00`; nến cuối đã đóng ở `13:00`. Request tới lúc `13:40` vẫn có cutoff `13:00` nhưng giờ mục tiêu forecast đã bắt đầu. Luôn đọc `generated_at` và thông tin timing.

## 2. Contract daily forecast support

Public tool: `forecast_support` tại MCP **8010** và trong Analyst graph.

Input:

```json
{"symbol":"ETH","performance_days":30,"market_days":30,"trend_hours":168,"cutoff":null}
```

Có thể bỏ cutoff. Symbol chỉ nhận BTC/ETH; mỗi target có weight/scaler/bundle riêng.

| Output | Ý nghĩa |
| --- | --- |
| `forecast` | q10/q50/q90 return/close và target UTC daily candle |
| `recent_performance` | Rolling backtest causal, direction và MAE cùng baseline |
| `market_statistics`, `hourly_trend` | Aggregate deterministic, không do LLM tự tính |
| `data_readiness`, `data_freshness`, `lineage` | Coverage, sync decision và batch IDs |
| `model` | Run/version/snapshot/feature order và checksum bundle |

Không gọi q10–q90 là “80% chắc chắn”; đọc empirical coverage trong cùng window.
Service fail-closed khi source/schema/checksum/context không khớp và không fallback ETH sang BTC.

## 3. Contract anomaly

> **Production-disabled:** `market_anomaly`, `detect_market_anomaly` và `/anomaly` không được đăng ký vào MCP, Analyst tool map hoặc Desk command. Implementation dưới đây được giữ lại cho thử nghiệm offline.

Contract thử nghiệm trước đây: `market_anomaly` tại MCP 8020, nội bộ là `detect_market_anomaly`. Nó khác `detect_btc_anomalies` tại MCP 8010, vốn chỉ dùng MAD.

Input gồm `symbol=BTC|ETH` bắt buộc và cutoff tùy chọn. Hai Forest độc lập chấm nến hourly và daily đã đóng gần nhất; đây là **phát hiện hiện trạng**, không phải dự báo anomaly tương lai.

| Output | Ý nghĩa |
| --- | --- |
| `sources.hourly`, `sources.daily` | Nguồn, cutoff, raw candle count và snapshot hash của từng frequency |
| `hourly`, `daily` | Hai kết quả từ bundle đúng asset/frequency; không fuse input giữa coin |
| `score`, `threshold`, `is_anomaly` | Score lớn hơn là khác thường hơn; flag khi score >= ngưỡng calibration |
| `largest_feature_deviations` | Feature lệch median/IQR train nhiều; không phải causal attribution của forest |
| `offline_evaluation` | Alert rate và future-risk lift; không phải labeled accuracy |
| `summary.risk_state` | Tóm tắt flag hai horizon; `decision` luôn null ở phase này |

Isolation Forest học không giám sát, không cần label normal/anomaly. Không có labeled ground truth nên không công bố accuracy/precision/recall. Anomaly thị trường không đồng nghĩa dữ liệu sai, cũng không phải tín hiệu mua/bán.

## 4. Contract model health (production-disabled)

`model_health` không còn được advertise qua MCP, Desk hoặc reasoning-agent tool map. Implementation cũ vẫn được giữ để nghiên cứu offline. Nó phụ thuộc reference artifact của anomaly/hourly model và không đại diện cho daily quantile model hiện tại. Anomaly drift lấy 336 nến để tạo khoảng 168 feature rows; forecast drift cũ lấy lịch sử dài hơn. Cả hai là PSI, tách biệt với lỗi forecast đã realized trong ledger. Chi tiết tại [model integration](model_integration.md).

- `data_drift`: danh sách feature/PSI/watch flag.
- `drift_watch`: có feature vượt ngưỡng heuristic hay không.
- `forecast_drift`: PSI của compact BTC forecast inputs với reference artifact riêng; response liệt kê phần chưa bao phủ.
- `live_performance`: n, MAE, relative MAE và direction từ prospective ledger; có thể `insufficient_data` hoặc `unavailable`. Không thay bằng metric hồi cứu.
- `frozen_forecast_test`: metric nghiên cứu hồi cứu, không biến thành current performance.

Ngưỡng PSI 0,25 là watch heuristic; không phải p-value hay chứng minh model hỏng. Không có rule tự retrain khi flag bật. Có schema/recorder không chứng minh service ledger đang hoạt động hoặc đã đủ mẫu.

## 5. Danh sách tool của hai reasoning agent

Các tool này là danh sách cho phép nội bộ, **không phải tất cả đều được public trực tiếp qua MCP**.

| Chủ thể | Tool | Dùng làm gì? |
| --- | --- | --- |
| Analyst | `market_data` | API market snapshot, live summary, daily direction/evaluation |
| Analyst | `forecast_support` | Daily BTC/ETH support qua A2A |
| Analyst | `detect_market_anomaly` | **Production-disabled**; BTC/ETH hourly + daily Isolation Forest được giữ offline |
| Analyst | `model_health` | **Production-disabled**; implementation PSI cũ giữ offline |
| Analyst | `investigate_warehouse` | Giao câu hỏi cho Operations qua A2A |
| Operations | `warehouse_status` | ETL batch states |
| Operations | `warehouse_coverage` | Giờ thiếu/trùng, asset/source grain |
| Operations | `warehouse_lineage` | Archive/hash và batch nguồn |
| Operations | `warehouse_reconciliation` | Staging = rejected + duplicate + accepted |
| Operations | `warehouse_quality` | DQ checks đã lưu |
| Operations | `warehouse_mart_parity` | Fact totals so mart subtotal |
| Operations | `airflow_status` | Đọc DAG/run từ Airflow 3 |
| Operations | `service_health` | HTTP, Airflow/Kafka status, PostgreSQL và stream freshness |
| Operations | `model_health` | **Production-disabled**; implementation PSI cũ giữ offline |
| Operations | `search_traces`, `inspect_trace` | Jaeger timing/error metadata có giới hạn |
| Cả hai | `load_skill`, `save_memory` | Skill instructions và ghi chú theo user, không phải market observation |

MCP 8020 chỉ công bố **`load_skill`, `ask_analyst`, `ask_operations`**. MCP 8010 công bố **`forecast_support`, `detect_btc_anomalies`**. `model_health` và `market_anomaly` hiện không được đăng ký public.

## 6. Contract hỏi agent và giao tiếp A2A

Public MCP `ask_analyst` / `ask_operations` nhận:

```json
{"question": "Kiểm coverage BTC 24 giờ và mart parity", "symbol": "BTC"}
```

A2A request validator nhận một JSON data part, question 1–3.000 ký tự, symbol `BTC|ETH|SOL`, và các field history/model/user được schema cho phép; không nhận field tùy ý. API tự gắn user đã xác thực, không tin user key từ browser. Forecast hỗ trợ BTC và ETH; anomaly và drift legacy đều bị tắt; các tool warehouse có phạm vi asset riêng.

Task: tạo → working → completed kèm JSON artifact, hoặc failed. Reply có `task_id`, `context_id`, `result`; phần result có `answer`, `evidence`, `llm_calls`, `usage`, `routing`, `limitations`. Delegation tạo task peer riêng, không phải gọi detector trong cùng hàm rồi gắn nhãn A2A.

Tool phải nằm trong danh sách của role và đúng JSON schema trước khi chạy. Tool thất bại trở thành evidence `unavailable`, không bịa số liệu. Hết graph deadline/budget hoặc toàn bộ route hỏng được báo rõ. Task không bền vững qua restart; chưa hỗ trợ continuation/cancel/resume đầy đủ.

## 7. Contract router

`Router.converse()` nhận hội thoại kiểu Converse + tool schema, trả lại assistant message cùng format và metadata route. Nó có thể dùng Bedrock hoặc chuyển sang chat-completions của Groq/OpenRouter rồi chuyển ngược output.

**Router không chạy tool.** Tool-call ID và argument object phải được giữ để graph trả tool result về đúng lời gọi. Schema/allowlist vẫn được kiểm ở graph sau khi provider trả lời.

Provider lỗi 4xx/5xx, timeout hoặc output không dùng được → route tiếp theo; cooldown và deadline được áp dụng. Hết route → `RouterUnavailable`. Không có lời hứa mọi model cho câu trả lời giống nhau. [Chi tiết cấu hình](model_router.md).

## 8. Contract @agent và slash command

Trade là tên giao diện của Analyst; SRE là tên giao diện của Operations. Prefix được parse có chủ đích, không giao LLM đoán tên agent. `POST /v1/agent/command` chỉ cho phép ba command production (`trade`, `sre`, `predict`) và asset hợp lệ. Slash ML không gọi LLM; `@trade`/`@sre` gọi đúng peer A2A. API nhận thêm `thread_id` và `model` tùy chọn; user lấy từ server authentication. Response có `run_id` và `thread_id` để đọc history/feedback. Input sai trả 422; auth/quota/owner checks chạy trước model. [Cách dùng](desk_commands.md).

## 9. Contract dữ liệu lên web

`app/api_schemas.py` định nghĩa envelope và provenance/quality cho dữ liệu app; nó khác artifact A2A. Đọc [giao ước dữ liệu & API](data_contracts_v1.md) cho schema API, [forecast giờ](hourly_forecast_contract.md) cho thiết kế nghiên cứu và [đọc code](code_guide.md) để tìm implementation.
