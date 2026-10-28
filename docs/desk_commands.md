# Dùng Desk và agent

Gõ câu hỏi bình thường để Analyst tự chọn tool. `@` gọi một agent, `/` chạy thẳng một tool. Model ML tính số; agent LLM chọn công cụ và giải thích kết quả.

## 1. Chọn đúng tác vụ

| Input | Điều gì chạy? | Ví dụ |
| --- | --- | --- |
| Câu hỏi thường hoặc `@trade` | Trade; có thể giao warehouse/SRE cho Operations | `Tóm tắt BTC bằng dữ liệu hiện tại và nói rõ phần thiếu` |
| `@sre` | Operations với tools chỉ đọc | `@sre Kiểm coverage BTC 24 giờ, quality và mart parity` |
| `/predict BTC` | Frozen hourly forecast, không gọi LLM | Dự báo return, không phải xác suất |
| `/anomaly BTC` | **Đã tắt trong production**; code thử nghiệm vẫn được giữ | Không còn được API/UI chấp nhận |
| `/drift BTC` | **Đã tắt trong production**; implementation PSI cũ vẫn được giữ offline | Phụ thuộc artifact anomaly/hourly cũ, không đại diện daily quantile model hiện tại |
| `/tools` | Help ngay trong browser | Xem cú pháp |

Agent reasoning hỗ trợ asset context BTC/ETH/SOL. `/predict` nhận BTC/ETH. Câu hỏi không phải quyền thực thi: agent không đặt lệnh, restart, backfill hoặc retrain.

## 2. Hội thoại, model và memory

Thanh dưới tiêu đề: chọn model, rồi ba nút biểu tượng.

| Nút | Việc |
| --- | --- |
| Bút chì | Hội thoại mới |
| Đồng hồ | Lịch sử hội thoại; server lấy các lượt trước của đúng user làm context, agent vẫn gọi tool cho trạng thái hiện tại |
| Bookmark | Memory: ghi chú ngắn theo user, xem/xóa được; agent chỉ lưu khi bạn yêu cầu hoặc nêu sở thích lâu dài |

- **Model picker:** Auto (router chọn theo tier) hoặc ghim một model được phép. Chi tiết ở [model router](model_router.md).
- **Thumbs up/down:** feedback lưu theo câu trả lời; owner xem trong Admin.
- Khách chưa đăng nhập có vài câu miễn phí, chỉ dùng model miễn phí, không có lịch sử/memory. Xem [đăng nhập](auth_setup.md).

## 3. Đọc một câu trả lời

| Phần | Ý nghĩa |
| --- | --- |
| Dòng meta | Model đã trả lời, hoặc "Tool result · no AI model" với lệnh `/` |
| Dòng bước | Agent đã làm gì theo thứ tự, ví dụ `Checked the forecast → Read the forecast explainer guide → Answered · 4.0 s`; bảng chi tiết mở ngay dưới |
| Câu in đậm | Câu trả lời; tiếp theo tối đa một bảng nhỏ và một dòng lưu ý |
| Ô dự báo | Viền vàng nét đứt, nhãn FORECAST, mức thay đổi dự kiến; giá thật (last close) là ô viền liền |
| Kiểm tra mô hình | Kết luận Stable / Shifting / Changed, rồi ba đầu vào thay đổi nhiều nhất bằng tên dễ hiểu; tên kỹ thuật nằm trong "All inputs (technical)" |
| Bất thường | Normal / Unusual và một thanh đo so với mức cảnh báo |
| Chip `Skill · Service health check` | Hướng dẫn agent đã theo; bấm để đọc nội dung skill |
| Nút lựa chọn | Khi câu hỏi không rõ đối tượng ("có ổn không?"), agent hỏi lại một câu và đưa 2–3 lựa chọn; bấm để gửi |

- Giờ hiển thị theo múi giờ của trình duyệt ("17:00 today", "15:46 yesterday"); JSON gốc giữ nguyên giá trị.
- Biểu đồ lấy số từ tool evidence, không từ câu văn của model. [Evidence & guardrails](response_guardrails.md) định nghĩa các trạng thái.
- **Trace (chỉ owner):** "Show request trace" trong Command details vẽ thời gian của request: model viết, lần gọi model thất bại (nhà cung cấp và lý do), tool, chuyển giao giữa agent. Jaeger vẫn chỉ chạy trong mạng ở nhà; xem [tracing](observability.md).

## 4. Điều khiển cửa sổ

Enter gửi, Shift + Enter xuống dòng. Hai biểu tượng ở góc tiêu đề: float/dock và mở rộng. Kéo tiêu đề để di chuyển khi float, kéo cạnh để đổi cỡ. Vị trí lưu trong trình duyệt; hội thoại lưu ở server.

## 5. Khi có lỗi

| Hiện tượng | Cách kiểm tra |
| --- | --- |
| `401` hoặc đăng nhập lặp | [Lỗi đăng nhập](auth_setup.md#9-lỗi-thường-gặp) |
| `429` | Hết lượt của user hoặc provider; đọc lý do, không tạo thêm key cùng tài khoản để né quota |
| `503` / "Agent/tool service unavailable" | Thường là mọi model miễn phí đều bận (Groq, OpenRouter trả 429); khách không được dùng model trả phí. Đăng nhập hoặc thử lại sau vài phút |
| Dự báo không có số | Kiểm artifact, nến đã đóng và độ mới dữ liệu; không bỏ qua validation |
| Agent nói chưa xác minh được | Mở dòng bước và evidence, xem nguồn nào thiếu |

API và field của tool ở [agent contracts](agent_contracts.md); luồng code ở [code guide](code_guide.md).
