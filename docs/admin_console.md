# Admin console

Màn hình cho owner xem ai dùng agent, hỏi gì, câu trả lời và model hoạt động ra sao.

## Ai thấy được

Owner là email trong `AGENT_OWNER_EMAILS`, và user `local` khi chạy trên máy. Owner thấy nút **Admin**
trên thanh trên cùng. API `/v1/admin/*` trả 403 cho người khác, kể cả khi họ tự gõ URL.

## Các tab

| Tab | Xem gì |
|---|---|
| Overview | Số user, câu hỏi, tỉ lệ lỗi, latency p50/p95, token, chi phí model trả phí, feedback, số lần bị giới hạn, tool hay được gọi, biểu đồ theo ngày |
| Conversations | Tìm trong câu hỏi và câu trả lời; lọc theo trạng thái, feedback, user; mở một run để xem từng bước, tool, model, token, trace ID |
| Users | Mỗi user: lần đầu/cuối, số câu hỏi, số cuộc trò chuyện, dùng model trả phí, lỗi, bị từ chối, feedback |
| Models | Mỗi model: số lần gọi, latency, token, số lần trả lời sau fallback, điểm eval; các lần thử lỗi |
| System | Độ chính xác live của dự báo (prediction ledger), lỗi agent gần đây |

Cửa sổ thời gian: 24 giờ, 7, 30 hoặc 90 ngày.

## Dữ liệu lấy từ đâu

| Bảng | Ghi gì | Ghi khi nào |
|---|---|---|
| `meta.agent_run` | Mỗi lệnh: câu hỏi, câu trả lời, bước, tool, model, token, latency, lỗi | Sau mỗi `/v1/agent/command` |
| `meta.agent_feedback` | Hữu ích / không hữu ích, kèm ghi chú | User bấm nút dưới câu trả lời |
| `meta.agent_refusal` | Yêu cầu bị giới hạn từ chối (HTTP 429) | Khi `app/usage.py` từ chối |
| `meta.app_user` | `user_key` → email, provider, lần đầu/cuối | Mỗi lần user đã đăng nhập mở app |

User đăng nhập hiện bằng email. Khách chưa đăng nhập chỉ là khóa `a_…`, băm từ IP. Code ở
[`app/admin.py`](../app/admin.py), migration `008_admin.sql` và `009_app_user.sql`.

## Feedback thành eval case

Câu trả lời bị đánh giá "không hữu ích" là ứng viên cho eval case mới: lọc **Feedback → Rated down**
trong Conversations, đọc ghi chú, rồi viết case trong `evals/cases.py` với đáp án từ warehouse.
Xem [Đánh giá agent](evaluation.md).
