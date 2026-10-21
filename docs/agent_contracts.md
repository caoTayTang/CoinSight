# Contract model, tool và agent

Contract là điều kiện input được chấp nhận, ý nghĩa output và cách báo lỗi. Đọc nó trước khi nối UI hoặc đổi feature. Nguồn chính là schema/validator và test, không phải tên service.

## 1. Contract nến và thời gian

Nguồn: `agents/domain.py`, `agents/market.py`, `warehouse_agents/market.py`.

Một nến có `open_time`, `open_price`, `high_price`, `low_price`, `close_price`, `volume_quote`, `trade_count`. Giá phải dương và hữu hạn; volume/trades không âm; OHLC phải nằm trong biên hợp lệ. Timestamp có timezone, đúng mốc giờ và được chuẩn hóa UTC.

`CandleContext` dùng đúng **169 nến liên tục trước cutoff**, thứ tự tăng. Không chấp nhận giờ tương lai hoặc nến chưa đóng. Cutoff là ranh giới kết thúc cửa sổ dữ liệu, không phải thời điểm request đến server.

Ví dụ minh họa: cutoff `2026-10-19T13:00:00Z` dùng nến mở từ 169 giờ trước tới `12:00`; nến cuối đã đóng ở `13:00`. Request tới lúc `13:40` vẫn có cutoff `13:00` nhưng giờ mục tiêu forecast đã bắt đầu. Luôn đọc `generated_at` và thông tin timing.

## 2. Contract forecast BTC giờ

Public tool: `predict_hourly` tại MCP **8010**. Agent LLM cũng có tool nội bộ cùng tên, gọi service forecast đó.

Input:

```json
{"cutoff": "2026-10-19T13:00:00Z"}
```

Có thể bỏ cutoff để lấy ranh giờ đóng mới nhất; ví dụ trên là timestamp lịch sử minh họa. Bộ forecast cần BTC và ETH cùng cutoff; model/feature/schema đã đóng băng.

| Output | Ý nghĩa |
| --- | --- |
| `model_id`, `bundle_payload_sha256` | Danh tính model/bundle đã dùng |
| `cutoff`, `target_open`, `target_close` | Cửa sổ dữ liệu và giờ cần dự báo |
| `generated_at`, `timing`, `target_already_started` | Thời điểm sinh dự báo so với giờ mục tiêu |
| `predicted_log_return` | Dự báo `log(close mục tiêu / reference close)` |
| `reference_close_usdt`, `predicted_close_usdt` | Giá tham chiếu và giá suy ra bằng hàm exp |
| `direction` | Dấu của return dự báo; không phải xác suất |
| `anomaly`, `anomaly_task_id`, snapshot/context hash | Kết quả peer MAD và bằng chứng cùng context |
| `research_test` | Metric hồi cứu được gắn nhãn rõ, không phải metric realtime |

Không được diễn giải `predicted_log_return` là confidence/accuracy. Service fail khi nguồn, schema, checksum hoặc peer context không khớp; không bịa dự báo fallback. CatBoost ensemble là phép tổ hợp cố định, không nằm trong router LLM.

## 3. Contract anomaly

Public tool mới: **`market_anomaly` tại MCP 8020**. Nội bộ: `detect_market_anomaly`. Nó khác `detect_btc_anomalies` tại MCP 8010, vốn chỉ dùng MAD.

Input là cutoff tùy chọn như trên. Forest chấm nến đã đóng gần nhất; đây là **phát hiện hiện trạng**, không phải dự báo anomaly của giờ tương lai.

| Output | Ý nghĩa |
| --- | --- |
| `source` | Nguồn, cutoff, raw candle count, snapshot hash, observed time |
| `trained.method`, `model_sha256` | Phương pháp và binary model đã dùng |
| `trained.score`, `threshold`, `is_anomaly` | Score lớn hơn là khác thường hơn; flag khi score >= ngưỡng |
| `largest_feature_deviations` | Feature lệch median/IQR nhiều; không phải causal attribution của forest |
| `mad_baseline` | Kết quả phương pháp MAD trên cùng input |

Isolation Forest học không giám sát, không cần label normal/anomaly. Không có labeled ground truth nên không công bố accuracy/precision/recall. Anomaly thị trường không đồng nghĩa dữ liệu sai, cũng không phải tín hiệu mua/bán.

## 4. Contract model health

Public tool: `model_health`, MCP 8020. Lấy 336 nến để tạo khoảng 168 feature rows, so phân bố với reference training bằng PSI.

- `data_drift`: danh sách feature/PSI/watch flag.
- `drift_watch`: có feature vượt ngưỡng heuristic hay không.
- `performance_status`: hiện chưa có prospective ledger để tính MAE mới.
- `frozen_forecast_test`: metric nghiên cứu hồi cứu, không biến thành current performance.

Ngưỡng PSI 0,25 là watch heuristic; không phải p-value hay chứng minh model hỏng. Không có rule tự retrain khi flag bật.

## 5. Danh sách tool của hai reasoning agent

Các tool này là danh sách cho phép nội bộ, **không phải tất cả đều được public trực tiếp qua MCP**.

| Chủ thể | Tool | Dùng làm gì? |
| --- | --- | --- |
| Analyst | `predict_hourly` | Gọi forecast cố định qua A2A |
| Analyst | `detect_market_anomaly` | Forest + MAD |
| Analyst | `model_health` | Drift / giới hạn performance |
| Analyst | `investigate_warehouse` | Giao câu hỏi cho Operations qua A2A |
| Operations | `warehouse_status` | ETL batch states |
| Operations | `warehouse_coverage` | Giờ thiếu/trùng, asset/source grain |
| Operations | `warehouse_lineage` | Archive/hash và batch nguồn |
| Operations | `warehouse_reconciliation` | Staging = rejected + duplicate + accepted |
| Operations | `warehouse_quality` | DQ checks đã lưu |
| Operations | `warehouse_mart_parity` | Fact totals so mart subtotal |
| Operations | `airflow_status` | Đọc DAG/run từ Airflow 3 |
| Operations | `service_health` | Reachability HTTP endpoint đã cấu hình |

MCP 8020 chỉ công bố **`market_anomaly`, `model_health`, `ask_analyst`, `ask_operations`**. MCP 8010 công bố **`predict_hourly`, `detect_btc_anomalies`**.

## 6. Contract hỏi agent và giao tiếp A2A

Public MCP `ask_analyst` / `ask_operations` nhận:

```json
{"question": "Kiểm coverage BTC 24 giờ và mart parity", "symbol": "BTC"}
```

A2A request validator nhận một JSON data part, question 1–3.000 ký tự, symbol `BTC|ETH|SOL`, không có field thừa. Symbol ở request không có nghĩa forecast/anomaly đã hỗ trợ ETH/SOL: hai tool ML hiện chấm BTC; các tool warehouse có phạm vi asset riêng.

Task: tạo → working → completed kèm JSON artifact, hoặc failed. Reply có `task_id`, `context_id`, `result`; phần result có `answer`, `evidence`, `llm_calls`, `usage`, `routing`, `limitations`. Delegation tạo task peer riêng, không phải gọi detector trong cùng hàm rồi gắn nhãn A2A.

Tool phải nằm trong danh sách của role và đúng JSON schema trước khi chạy. Tool thất bại trở thành evidence `unavailable`, không bịa số liệu. Hết graph deadline/budget hoặc toàn bộ route hỏng được báo rõ. Task không bền vững qua restart; chưa hỗ trợ continuation/cancel/resume đầy đủ.

## 7. Contract router

`Router.converse()` nhận hội thoại kiểu Converse + tool schema, trả lại assistant message cùng format và metadata route. Nó có thể dùng Bedrock hoặc chuyển sang chat-completions của Groq/OpenRouter rồi chuyển ngược output.

**Router không chạy tool.** Tool-call ID và argument object phải được giữ để graph trả tool result về đúng lời gọi. Schema/allowlist vẫn được kiểm ở graph sau khi provider trả lời.

Provider lỗi 4xx/5xx, timeout hoặc output không dùng được → route tiếp theo; cooldown và deadline được áp dụng. Hết route → `RouterUnavailable`. Không có lời hứa mọi model cho câu trả lời giống nhau. [Chi tiết cấu hình](model_router.md).

## 8. Contract @agent và slash command

Trade là tên giao diện của Analyst; SRE là tên giao diện của Operations. Prefix được parse có chủ đích, không giao LLM đoán tên agent. `POST /v1/agent/command` chỉ cho phép năm command và asset hợp lệ. Slash ML không gọi LLM; `@trade`/`@sre` gọi đúng peer A2A. [Chi tiết contract HTTP và ví dụ](desk_commands.md).

## 9. Contract dữ liệu lên web

`app/api_schemas.py` định nghĩa envelope và provenance/quality cho dữ liệu app; nó khác artifact A2A. Đọc [giao ước dữ liệu & API](data_contracts_v1.md) cho schema API, [forecast giờ](hourly_forecast_contract.md) cho thiết kế nghiên cứu và [đọc code](code_guide.md) để tìm implementation.
