# CoinSight hiện tại: có gì và điều khiển ở đâu?

Bản tổng hợp ngày **19/10/2026**. Đây là trạng thái đã kiểm chứng trong lần phát triển gần nhất, **không phải màn hình health trực tiếp**. Bắt đầu từ trang này; các báo cáo nghiên cứu cũ dùng để truy lại thí nghiệm.

## 1. Bốn phần cần phân biệt

| Phần | Làm gì? | Bạn điều khiển bằng gì? |
| --- | --- | --- |
| **Kho dữ liệu** | Nạp lịch sử và nến trực tiếp, staging → kiểm tra → fact/mart, lưu lineage | Compose chính, API và workspace Operations |
| **Dự báo BTC giờ** | Hai CatBoost đã train, tổ hợp cố định; dự báo log return giờ tiếp theo | MCP dự báo tại cổng 8010; không dùng key LLM |
| **Phát hiện bất thường** | Isolation Forest đã train + MAD đối chiếu; chấm nến BTC vừa đóng | Tool `market_anomaly` tại MCP 8020 |
| **Agent phân tích** | LLM chọn tool, đọc bằng chứng, trả lời; Analyst có thể nhờ Operations qua A2A | MCP 8020, cấu hình router và key trong `.env` |

**Đổi LLM không train lại CatBoost hoặc Isolation Forest.** LLM giải thích và chọn công cụ; giá trị dự báo và anomaly score được tính bởi các model/tool riêng.

## 2. Đường đi hiện tại

```text
Ứng dụng web :3000
  ├─ Market / Operations → API :8000 → warehouse + stream
  ├─ Desk plain text → /v1/agent/command → Analyst (tự chọn tool, giao Operations khi cần)
  ├─ Desk @trade / @sre /tool → API /v1/agent/command → extension
  └─ Docs → tài liệu trong bản build frontend

Bộ tool dự báo riêng
  MCP :8010 → Prediction A2A :8011 → MAD A2A :8012
                     └─ hai CatBoost cố định

Bộ agent phân tích riêng
  MCP :8020
    ├─ market_anomaly → Isolation Forest + MAD
    ├─ model_health → feature drift
    ├─ ask_analyst → Analyst :8021 [LangGraph + router LLM]
    │                  ├─ tool dự báo / anomaly / drift
    │                  └─ A2A → Operations :8022 [LangGraph + router LLM]
    └─ ask_operations ─────────────┘
                                 └─ tool chỉ đọc DB / Airflow / service
```

**Ranh giới quan trọng:** Desk đã có `@trade`, `@sre` và slash tool để gọi bộ agent mới. Plain text không có prefix đi tới Analyst: agent tự chọn tool thị trường và giao câu hỏi kho dữ liệu/SRE cho Operations. Đường chat Bedrock cũ đã bỏ; mọi câu hỏi dùng router đa provider. [Cách dùng lệnh](desk_commands.md).

Desk có giao diện gõ lệnh và xem evidence; trang docs là hướng dẫn. Hiện **chưa có giao diện chỉnh key, model hoặc bật/tắt router**. Không có tác vụ giao dịch hay tự sửa warehouse.

## 3. Đã kiểm chứng tới đâu?

| Hạng mục | Trạng thái / bằng chứng | Giới hạn |
| --- | --- | --- |
| Kho dữ liệu, API, web và stream | Đã có mã nguồn và service; xem trang [Bằng chứng warehouse](warehouse_proof.md) | Container chạy không đồng nghĩa dữ liệu đủ/mới; phải đọc coverage, lineage và parity |
| Forecast giờ BTC | Đã train, đóng băng bundle và phục vụ qua MCP/A2A; 6.984 forecast 2026 được đối chiếu khi export | Relative MAE hồi cứu khoảng **0,997017**, chỉ cải thiện nhỏ so với zero-return; không phải accuracy |
| Isolation Forest | Train 2023–2024: **17.375** dòng; calibration 2025: **8.760**; test hồi cứu: **6.984** giờ | Không có nhãn anomaly thật để tính precision/recall/accuracy |
| Anomaly đối chiếu | Forest **78 cảnh báo (1,1168%)**; MAD **101 (1,4462%)**, cùng timestamp | Ít cảnh báo hơn không chứng minh tốt hơn |
| Analyst → Operations | **Đã pass toàn luồng thật** MCP → LLM → A2A → tool → trả lời | Chỉ đọc; không có bộ nhớ dài hạn hay tự phục hồi tác vụ qua restart |
| Router / Desk command | **65 test agent/bridge/guardrail pass**, 3 test DB bỏ qua; **24 test frontend** và **8 test proxy API** pass. DB đã có lần test tách biệt trước đó | Không phải chứng nhận production công khai hoặc phép đo SLA |
| Provider thật | Groq gọi thành công; Gemma Free trả **429**, chuyển Haiku thành công **200**; Nova đã từng pass | Đây là kết quả lần kiểm tra, không bảo đảm provider luôn sẵn sàng |
| Warehouse Operations tools | Coverage, lineage, reconciliation, quality, fact/mart parity; test bằng DB PostgreSQL riêng | Chưa audit đầy đủ quyền/kết nối của warehouse đang chạy sau mọi thay đổi |
| Airflow / SRE | Có tool đọc Airflow 3 API và probe HTTP | Cần URL/token hợp lệ; không tự có Kafka lag, disk metrics, hay quyền restart DAG |

Nghiên cứu 2025/2026 đã được xem nhiều lần: đây là đánh giá hồi cứu, không được gọi là phép kiểm tương lai mới. Chưa nối sổ dự báo bất biến với kết quả thực tế để báo MAE production đang chạy.

## 4. Tôi muốn làm việc này thì chỉnh đâu?

| Muốn làm gì? | Nơi điều khiển | Phạm vi ảnh hưởng |
| --- | --- | --- |
| Đọc tổng quan giá, dữ liệu và warehouse | [Mở ứng dụng](/) → Market / Operations | UI/API chính |
| Chọn provider, model, thứ tự vòng xoay | `warehouse_agents/router.json` | Hai agent LLM mới |
| Điền key | `.env` ở root repo; xem [hướng dẫn router](model_router.md) | Key chỉ được nạp vào container sau recreate; không dán vào chat |
| Dùng tool / hỏi hai agent | Desk `@trade` / `@sre` / slash tool hoặc MCP `http://localhost:8020/mcp` | Bộ agent phân tích |
| Chỉ gọi forecast giờ | MCP `http://localhost:8010/mcp` | Bộ tool dự báo, không cần LLM |
| Kiểm tra model drift | MCP 8020 → `model_health` | PSI trên feature; không tự tính current MAE |
| Đổi kết nối warehouse / Airflow cho Operations | `WAREHOUSE_AGENT_DATABASE_URL`, `WAREHOUSE_AGENT_AIRFLOW_URL`, `AIRFLOW_API_TOKEN` trong `.env` | Tool Operations |
| Train lại anomaly / forecast | Quy trình nghiên cứu riêng và version artifact mới | Không phải thao tác đổi model LLM; hiện không có nút tự retrain |

Các key `_2` là slot tùy chọn cho key thứ hai. Router không tự tạo key. Nhiều key có thể dùng chung quota tài khoản.

## 5. Nên routing model như thế nào?

**Có, hiện đã routing cả provider lẫn model.** Một route là cặp `provider + model` và tham chiếu key. Cấu hình hiện tại dùng round-robin:

```text
Groq GPT-OSS 120B → OpenRouter Gemma 4 31B Free → Bedrock Haiku 4.5 → Nova 2 Lite
         ↑____________________________________________________________|
```

Mỗi lượt gọi LLM bắt đầu ở route kế tiếp; thiếu key/cooldown thì bỏ qua, lỗi thì đi tiếp. Analyst và Operations xoay độc lập; một câu hỏi có thể cần nhiều lượt LLM và nhiều provider.

**Khuyến nghị vận hành:** giữ round-robin trong giai đoạn demo/thử quota như bạn đã chọn. Khi cần đánh giá độ nhất quán câu trả lời, chuyển `strategy` sang `priority`, dùng một model chính và các model còn lại làm dự phòng. Thay model theo năng lực từng tác vụ là một lựa chọn khác, **chưa được triển khai**. Chưa có bằng chứng để nói phương án đó tốt hơn cho dự án này.

Round-robin chia tải, không phải bộ giới hạn RPM toàn hệ thống và không tăng quota chung. Hội thoại, tool schema và bằng chứng có thể được gửi sang các provider được cấu hình. [Xem cách chỉnh và áp dụng](model_router.md).

## 6. Việc tiếp theo, theo thứ tự

1. **Dùng lệnh rõ ràng trong Desk:** `@trade`, `@sre`, `/predict BTC`, `/anomaly BTC`, `/drift BTC`; plain text đi tới Analyst và agent tự chọn tool. Tiếp theo là đánh giá trải nghiệm dùng các lệnh này.
2. **Đo và hiển thị request thực:** provider/model đã chọn, failover, thời gian và chi phí; metadata router đã có trong Command details của Desk; chưa có dashboard quản trị quota/chi phí/model.
3. **Kiểm chứng Ops trên warehouse thật** và kết nối Airflow có quyền chỉ đọc; unavailable phải giữ nguyên trạng thái unavailable.
4. **Đo chất lượng agent**, không chỉ giao thức: câu trả lời có căn cứ, chọn đúng tool, xử lý nguồn thiếu/lỗi và so sánh model trên cùng bộ câu hỏi.
5. **Theo dõi forecast tương lai** nếu cần chứng minh giá trị dự báo; drift không thay được metric lỗi thực tế.

Không cần thêm agent hay thêm một tầng router nữa lúc này. Nên làm rõ đường điều khiển và đo phần đã có trước.

## 7. Đọc tiếp đúng chỗ

- [Desk: @trade, @sre và slash command](desk_commands.md): thao tác ngay trong web.
- [Đọc code theo request](code_guide.md): thứ tự file cần đọc.
- [Response, graph và guardrail](response_guardrails.md): cách hiển thị và giới hạn an toàn.
- [Contract model, tool và agent](agent_contracts.md): input/output, timing và báo lỗi.
- [Điều khiển agent và tool](agent_control.md): lệnh chạy/dừng, cổng, phạm vi và kiểm chứng.
- [Đổi key, model và router](model_router.md): cấu hình hiện tại, round-robin/priority, lỗi và cooldown.
- [Luồng dữ liệu](data_flow.md): nguồn → kho → API.
- [Bằng chứng warehouse](warehouse_proof.md): kiểm dữ liệu và load thật.
- [Forecast giờ: train/backtest](hourly_backtest.md): kết quả nghiên cứu và giới hạn.
- [Giới hạn & backlog](product_readiness.md): những điều chưa đủ để vận hành thực tế.


## SRE runbooks và drift

SRE có `search_runbooks` (BM25 local, source/hash/citation) và gọi trực tiếp `model_health`. Drift hiện là PSI của anomaly features; không là MAE hoặc drift toàn bộ CatBoost. [Hướng dẫn và giới hạn fine-tune/RAG](sre_rag.md). Unsloth chưa train trên GPU; dense/hybrid/reranker đã chạy CPU smoke benchmark, chưa có independent quality evaluation.
