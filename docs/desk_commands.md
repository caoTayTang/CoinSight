# Dùng Desk và agent

Gõ câu hỏi bình thường để Trade tự chọn tools. Dùng `@sre` khi muốn điều tra dữ liệu hoặc hạ tầng trực tiếp. Model ML tính số; agent LLM chọn công cụ và giải thích kết quả.

## 1. Chọn đúng tác vụ

| Input | Điều gì chạy? | Ví dụ |
| --- | --- | --- |
| Câu hỏi thường hoặc `@trade` | Trade; có thể giao warehouse/SRE cho Operations | `Tóm tắt BTC bằng dữ liệu hiện tại và nói rõ phần thiếu` |
| `@sre` | Operations với tools chỉ đọc | `@sre Kiểm coverage BTC 24 giờ, quality và mart parity` |
| `/predict BTC` | Frozen hourly forecast, không gọi LLM | Dự báo return, không phải xác suất |
| `/anomaly BTC` | Isolation Forest + MAD, không gọi LLM | Kiểm nến vừa đóng có khác thường không |
| `/drift BTC` | Model input drift và ledger, không gọi LLM | Metric thực chỉ có khi ledger đã được chạy và chấm đủ dữ liệu |
| `/tools` | Help ngay trong browser | Xem cú pháp |

Agent reasoning hỗ trợ asset context BTC/ETH/SOL. Các lệnh ML trực tiếp hiện chỉ nhận BTC. Câu hỏi không phải quyền thực thi: agent không đặt lệnh, restart, backfill hoặc retrain.

## 2. Hội thoại, model và memory

- **New / History:** bắt đầu thread mới hoặc mở thread đã lưu. Server lấy các lượt trước của đúng user để làm context; agent vẫn phải gọi tool cho trạng thái hiện tại.
- **Model picker:** chọn Auto hoặc pin model được tài khoản cho phép. Auto dùng fallback theo tier; quota có thể giới hạn paid routes. Chi tiết tại [model router](model_router.md).
- **Memory:** các ghi chú ngắn theo user, có thể xem/xóa. Agent lưu khi bạn yêu cầu hoặc nêu preference dài hạn; không dùng memory thay market evidence.
- **Thumbs up/down:** feedback cho câu trả lời đã lưu. Owner xem tổng hợp trong Admin; feedback chưa phải nhãn benchmark đã được review.

Visitor chưa đăng nhập có quota miễn phí nhưng không có history list/memory dài hạn. [Đăng nhập Google/GitHub](auth_setup.md) giải thích cách bật account và owner.

## 3. Đọc một câu trả lời

Xem model, steps, evidence status và timestamp. Tools trực tiếp có `0 LLM calls`. Một điều tra có thể gọi nhiều lượt hoặc fallback provider; token usage không phải hóa đơn đầy đủ.

Biểu đồ số lấy từ tool evidence, không từ câu văn model. Source citations mở skill đã load; chúng không chứng minh mọi kết luận đều đúng. Trace links mở Jaeger local và có thể điền câu hỏi nhờ SRE điều tra request đó. [Evidence & guardrails](response_guardrails.md) giữ định nghĩa các badge và giới hạn kiểm chứng.

## 4. Điều khiển cửa sổ

Enter gửi, Shift + Enter xuống dòng. Kéo header để float Desk, kéo divider/corner để resize, Dock để ghim lại hoặc Expand để đọc rộng hơn. Geometry được lưu local trong browser; conversation history được lưu riêng ở server. Light/Dark toggle không đổi dữ liệu hoặc agent.

## 5. Khi có lỗi

| Hiện tượng | Cách kiểm tra |
| --- | --- |
| `401` hoặc sign-in lặp | [Auth troubleshooting](auth_setup.md#9-lỗi-thường-gặp) |
| `429` | Quota user hoặc provider; đọc lý do, không tạo thêm key cùng tài khoản để né quota |
| `503` / tool unavailable | Extension, source hoặc provider chưa dùng được; [chạy local](running_system.md) |
| Forecast không có số | Kiểm artifact, closed candles và freshness; không bypass validation |
| Agent nói chưa xác minh được | Mở evidence/steps, kiểm nguồn bị thiếu thay vì coi câu trả lời là xác nhận hệ thống khỏe |

API schema và tool fields nằm ở [agent contracts](agent_contracts.md); luồng code ở [code guide](code_guide.md). Trang này chỉ giữ thao tác người dùng.
