# Câu trả lời, biểu đồ và guardrail

Desk hiển thị Markdown, sơ đồ giải thích và biểu đồ từ bằng chứng. Các lớp này có nhiệm vụ khác nhau: **LLM viết phần giải thích; tool trả số liệu; UI dựng biểu đồ số từ tool evidence**.

## 1. Thử các dạng trả lời

```text
/anomaly BTC
/drift BTC
/predict BTC
@sre Kiểm coverage BTC 24 giờ và tóm tắt bằng bảng
@trade Giải thích luồng forecast bằng sơ đồ Mermaid ngắn; phân biệt model ML và LLM
```

- Forecast: so hai giá trị reference/predicted close bằng thẻ số; không bịa một đường giá lịch sử.
- Anomaly: score Forest so ngưỡng cố định; score không phải xác suất crash.
- Drift: các PSI theo feature, có mốc watch 0,25; không gọi đó là MAE.
- Coverage: expected/observed/missing hours nếu tool trả dữ liệu hợp lệ, cân đối được số giờ.
- Mermaid: sơ đồ flow/sequence/state để giải thích cấu trúc; luôn gắn nhãn **schematic**, không phải quan sát đo được.

Biểu đồ được thêm khi evidence phù hợp có mặt, không tạo request provider/tool mới. Plain text và các lệnh agent hiện dùng cùng command/evidence path. History không thay thế việc đọc live tools cho claim hiện tại.

## 2. Markdown render

Có heading rõ, danh sách, bảng cuộn ngang, inline code, code block có nhãn ngôn ngữ và nút copy. Link ngoài mở tab mới với `noopener`, `noreferrer`, không gửi referrer. Raw HTML và ảnh/media nhúng từ response không được render.

Link chỉ cho phép HTTP/HTTPS hoặc đường dẫn docs/report nội bộ và anchor. Loại bỏ scheme thực thi, URL chứa user/password và query có dấu hiệu key/token/secret. Nếu link bị loại, giữ phần chữ và ghi `[link removed]`.

Giới hạn hiển thị 30.000 ký tự; tối đa 12 code block và hai sơ đồ mỗi response. Bảng tối đa 100 dòng dữ liệu, 12 cột. Đây là giới hạn hiển thị, không phải quy tắc đánh giá model.

## 3. Sơ đồ an toàn hơn

Chỉ bật Mermaid `flowchart`/`graph`, `sequenceDiagram`, `stateDiagram-v2` với tập cú pháp giới hạn. Directive/config, custom style, click/callback/link, HTML và cú pháp resource/image không được bật. Giới hạn 8.000 ký tự, 100 dòng và 80 cạnh cho một sơ đồ; có zoom/reset, scroll và xem source.

Mermaid chạy `securityLevel: strict`; SVG đầu ra được lọc thêm bằng DOMPurify, loại script, foreignObject, ảnh/link ngoài và animation. Sơ đồ lỗi hoặc bị chặn hiện thông báo và source thay vì làm mất cả câu trả lời. Không cho LLM chạy JavaScript/HTML qua code fence.

## 4. Trạng thái evidence có nghĩa gì?

| Nhãn | Ý nghĩa |
| --- | --- |
| `available` | Tool trả observation sử dụng được; **không phải chứng nhận mọi câu LLM viết đều đúng** |
| `partial` | Một phần tool unavailable/truncated; cần đọc giới hạn và evidence cụ thể |
| `unavailable` | Tất cả tool được gọi đều thiếu observation dùng được; kết luận LLM bị thay bằng thông báo chưa thể xác minh |
| `none` | Chưa gọi tool có trạng thái xác định; phần trả lời chỉ nên xem là giải thích, không phải quan sát thị trường/hệ thống đã kiểm chứng |

Delegation wrapper `status=available` không được che việc các tool bên trong đều unavailable. Badge do code tổng hợp từ trace, không để LLM tự gắn nhãn “đã xác minh”.

Biểu đồ chỉ nhận field số hữu hạn từ các tool đã biết, không đọc giá trị do LLM tự viết trong answer. Dữ liệu unavailable hoặc sai cấu trúc bị bỏ qua. Có phần Exact values và nguồn/cutoff để đối chiếu; tối đa bốn biểu đồ một response.

## 5. Guardrail của input và tool

- Chặn chuỗi giống key Bedrock/Groq/OpenRouter trước khi gửi model; các entry point server cũng kiểm tra, không chỉ frontend.
- Redact key đã cấu hình và các prefix key nhận diện được khỏi answer; lỗi validation chat không echo lại raw input.
- Tool sai argument bị chặn trước execution; lỗi schema trả danh sách field cho phép để model sửa và thử lại trong budget.
- Tool chỉ được gọi theo role allowlist và JSON schema; không có SQL/shell tùy ý hoặc quyền ghi.
- SQL parameterized và read-only; không tự restart DAG, retrain hay đặt lệnh giao dịch.
- Giới hạn lượt LLM, tool mỗi lượt, timeout, request body, rate, task retention và tài nguyên vẫn áp dụng.

Các key không nên được dán vào chat. Bộ nhận diện không phát hiện được mọi loại bí mật: nó dùng prefix phổ biến và giá trị key/token đã cấu hình, không phải hệ thống phân loại DLP tổng quát.

## 6. Những gì chưa được đảm bảo

Guardrail không chứng minh toàn bộ câu trả lời đúng, không loại được mọi prompt injection và không đánh giá khả năng sinh lời. Một tool trả available vẫn có thể được LLM diễn giải sai. Chưa có benchmark chuyên biệt đủ rộng cho hallucination, role escape hoặc chất lượng câu trả lời giữa các model trong vòng xoay.

Chặn HTML/SVG/URL là bảo vệ render; allowlist/read-only là bảo vệ hành động; evidence status là bảo vệ một số kết luận thiếu căn cứ. Không dùng một lớp thay cho các lớp còn lại. Không tự gọi nội dung “production-safe” chỉ vì một số test pass.

## 7. Đọc code ở đâu?

| Phần | File |
| --- | --- |
| Markdown + code block | `frontend/src/AgentResponse.jsx` |
| Policy URL/secret/diagram và chọn dữ liệu chart | `frontend/src/responsePolicy.js` |
| Biểu đồ từ tool | `frontend/src/ResponseCharts.jsx` |
| Mermaid + SVG sanitizer | `frontend/src/ResponseDiagram.jsx` |
| Evidence/secret guard của agent | `warehouse_agents/guardrails.py` |
| Prompt, allowlist, graph và áp dụng guard | `warehouse_agents/graph.py` |
| Desk proxy input-output guard | `app/response_guard.py`, `app/api.py`, `app/desk_commands.py` |
| Test | `frontend/src/responsePolicy.test.js`, `tests/warehouse_agents/test_guardrails.py`, `tests/app/test_desk_commands.py` |

[Đọc code theo request](code_guide.md) · [Contract](agent_contracts.md) · [Lệnh Desk](desk_commands.md)
