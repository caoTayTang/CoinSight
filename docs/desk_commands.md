# Desk: @trade, @sre và /tool

Mở [ứng dụng](/), vào Desk. Dùng `@` để chọn agent và `/` để gọi tool cụ thể. Gõ `@` hoặc `/` sẽ hiện các lựa chọn; có nút nhanh `@trade`, `@sre`, `/tools` ngay trên ô nhập.

## 1. Thử ngay

```text
/tools
@trade Dự báo BTC giờ, kiểm tra anomaly và giải thích giới hạn
@sre Kiểm coverage BTC 24 giờ, lineage và mart parity
/predict BTC
/anomaly BTC
/drift BTC
```

| Lệnh | Điều gì thực sự chạy? | Có gọi LLM? |
| --- | --- | --- |
| `@trade câu hỏi` | Analyst reasoning agent qua A2A; chọn forecast/anomaly/drift hoặc giao warehouse cho SRE | Có, dùng router |
| `@sre câu hỏi` | Operations reasoning agent qua A2A; đọc warehouse/Airflow/service | Có, dùng router |
| `/predict BTC` | Gọi ensemble hai CatBoost đã đóng băng qua prediction A2A | Không |
| `/anomaly BTC` | Isolation Forest + MAD trên nến vừa đóng | Không |
| `/drift BTC` | PSI feature + thông tin metric hồi cứu | Không |
| `/tools` | Danh sách lệnh và link code/contract ngay trong chat | Không, xử lý local |

`/trade câu hỏi` và `/sre câu hỏi` là cú pháp thay thế cho hai lệnh `@`. `@ops` không phải lệnh giao diện. Tên service/role trong code vẫn là `analyst` (Trade) và `operations` (SRE), để không đổi định danh giao thức và deployment hiện có.

Không cần tạo agent mới cho mỗi slash command. Các lệnh ML gọi đúng tool mà không yêu cầu LLM tự đoán ý định. Tên Trade vẫn là agent phân tích chỉ đọc; chưa có quyền đặt lệnh hay tự giao dịch.

## 2. Chọn coin và cách gửi

Agent nhận asset đang được chọn trên web (`BTC|ETH|SOL`). Các tool ML hiện chỉ hỗ trợ **BTC**: viết rõ `/predict BTC`, `/anomaly BTC`, `/drift BTC` để không nhầm với coin đang chọn. Nếu chỉ gõ `/anomaly` khi chọn ETH/SOL, UI báo lỗi thay vì lặng lẽ chấm BTC.

`@trade` và `@sre` cần câu hỏi phía sau; slash ML chỉ nhận asset, không nhận một đoạn yêu cầu tùy ý. Lệnh sai được báo rõ, không bị chuyển ngầm vào LLM chat cũ.

**Plain text không có `@` hoặc `/` đi tới Analyst** (như `@trade`): agent tự chọn tool thị trường và giao câu hỏi kho dữ liệu/SRE cho Operations. Dùng `@sre` để hỏi thẳng Operations.

Enter gửi; Shift + Enter xuống dòng. Các request là one-shot; UI hiện hội thoại nhưng backend agent chưa có bộ nhớ session dài hạn giữa các request.

## 3. Đọc kết quả và bằng chứng

Câu trả lời command có phần **Command details** mở ra được:

- Command, số lượt LLM và task ID nếu có agent/A2A.
- Provider/model của từng lượt gọi, chiến lược router và các lần chuyển dự phòng.
- Tool evidence dạng JSON để đối chiếu score, cutoff, hash hoặc số liệu warehouse.

Tool trực tiếp hiển thị `0 LLM calls`. Một request agent có thể có nhiều lượt LLM và đổi model giữa các lượt do round-robin. Usage của agent hiện là usage được trả từ các response thành công, không phải hóa đơn đầy đủ.

Biểu đồ số lấy từ evidence, không lấy từ câu văn của LLM. Anomaly/drift/forecast/coverage có cách trình bày riêng; Mermaid dùng cho sơ đồ giải thích. [Render, graph và guardrail](response_guardrails.md).

## 4. Đường mã nguồn sau một lệnh

```text
frontend/src/deskCommands.js          parse @ / và kiểm cú pháp
  → frontend/src/components.jsx     submit + hiển thị kết quả/evidence
  → POST /api/v1/agent/command       Nginx chuyển tới API
  → app/api.py + app/desk_commands.py
  → warehouse_agents/desk.py        validator + dispatch tool/peer
      ├─ @trade → Analyst A2A → graph → router + tools
      ├─ @sre   → Operations A2A → graph → router + tools
      └─ /tool  → tools/model cố định, không qua LLM
```

Đường API command không nhận URL, SQL hay tên tool tùy ý từ browser. Token dịch vụ nếu dùng được chuyển ở server; key provider không gửi xuống frontend. Gateway bridge dùng cùng validation/auth/body/rate limits với extension hiện có.

## 5. Contract HTTP

`POST /v1/agent/command` nhận:

```json
{"command":"sre","question":"Kiểm coverage BTC 24 giờ","symbol":"BTC"}
```

`command` chỉ nhận `trade|sre|predict|anomaly|drift`. Agent cần question không rỗng, tối đa 2.000 ký tự. Tool ML chỉ nhận BTC và question rỗng. Không nhận field thừa.

Response có `command`, `answer`, `evidence`, `routing`, `llm_calls`; request agent còn có `task_id`, `usage`. Invalid input trả 422; dependency/tool không hoạt động trả 503 đã rút gọn, không bịa số liệu. `/tools` không gọi endpoint này.

## 6. Nếu lệnh không chạy

Extension ở 8020–8022 phải chạy và bundle ML phải có. API dùng `WAREHOUSE_DESK_URL`, mặc định qua `host.docker.internal:8020/desk/command` trong Docker Desktop. Nếu bật `WAREHOUSE_AGENT_TOKEN`, API và extension phải dùng cùng token. Khi đổi token/key, recreate container liên quan để nạp biến mới.

Đây là giao diện điều khiển local theo request, chưa phải quản trị public có phân quyền nhiều người dùng. [Cách chạy service](agent_control.md) · [Đọc code](code_guide.md) · [Contracts](agent_contracts.md) · [Đổi model/router](model_router.md).
