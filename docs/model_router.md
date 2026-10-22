# Chọn provider, model và key

**Router hiện chọn cả provider lẫn model cho Analyst và Operations.** Nó không chọn giữa CatBoost và Isolation Forest, không đổi bài toán dự báo và phục vụ mọi câu hỏi trong Desk: plain text và `@trade` đi tới Analyst, `@sre` đi tới Operations.

## 1. Cấu hình hiện tại

File điều khiển: **`warehouse_agents/router.json`**. Chiến lược: **`round_robin` theo tầng (`tier`)**.

| Tầng | Provider | Model ID | Biến chứa key |
| --- | --- | --- | --- |
| 0 | Groq (mỗi key một slot, xoay vòng) | `openai/gpt-oss-120b` | `GROQ_API_KEY` (danh sách) |
| 1 | OpenRouter | `google/gemma-4-31b-it:free` | `OPENROUTER_API_KEY` |
| 2 | Bedrock (dự phòng cuối) | `global.anthropic.claude-haiku-4-5-20251001-v1:0` | `AWS_BEARER_TOKEN_BEDROCK` |

Model/provider cần được tài khoản cho phép và hỗ trợ tool calling.

## 2. Tầng và round-robin làm gì?

```text
Lượt LLM 1: groq#1 → (lỗi) groq#2 → groq#3 → OpenRouter → Haiku
Lượt LLM 2: groq#2 → ...
Lượt LLM 3: groq#3 → ...
Lượt LLM 4: groq#1 → ...
```

Router thử từng tầng, tầng thấp trước. Trong một tầng, `round_robin` xoay slot bắt đầu cho mỗi lượt gọi để chia tải giữa các key; `priority` giữ thứ tự trong file. Chỉ khi mọi slot của tầng 0 lỗi hoặc đang cooldown mới sang OpenRouter, rồi mới tới Haiku. Thiếu key hoặc slot đang cooldown thì bỏ qua; mỗi slot thử tối đa một lần trong một lượt gọi.

Analyst và Operations có **con trỏ và cooldown riêng trong process riêng**; restart đặt lại. Đây không phải bộ cân bằng quota dùng chung cho toàn hệ thống.

## 3. Nhiều key cho một provider

Một biến có thể chứa danh sách key; router tạo một slot cho mỗi key (`groq#1`, `groq#2`, …):

```env
GROQ_API_KEY=["gsk_...","gsk_...","gsk_..."]
```

Cũng chấp nhận dạng `k1,k2,k3` hoặc một key đơn. Không cần thêm route hay biến `_2`. Guardrail chặn và che **từng** key trong danh sách.

Giới hạn Groq tính **theo tài khoản (organization)**, không theo key: nhiều key cùng một tài khoản dùng chung quota. Key chỉ tăng dung lượng khi thuộc tài khoản khác, và chỉ dùng key mà chủ tài khoản đồng ý cho dùng.

**Ước lượng với 3 tài khoản Groq free** (mỗi tài khoản 8.000 token/phút, 200.000 token/ngày, 1.000 request/ngày). Một câu hỏi agent đo trên eval dùng trung bình **~3.400 token** (p90 ~6.000) qua ~2,2 lượt LLM:

| | 1 key | 3 key |
| --- | ---: | ---: |
| Câu hỏi/phút | ~2 | ~7 |
| Câu hỏi/ngày (giới hạn token) | ~58 | ~175 |
| Chạy eval 57 câu | gần hết quota ngày | ~1/3 quota ngày, ~8 phút |

## 4. Đổi key

Điền trong **`.env` ở root repo**, không đặt key thật trong `router.json`:

```env
GROQ_API_KEY=["gsk_...","gsk_..."]
OPENROUTER_API_KEY=your_key_here
AWS_BEARER_TOKEN_BEDROCK=your_key_here
```

## 5. Đổi model hoặc đổi vòng

Sửa `model` trong route tương ứng, di chuyển các entry trong mảng `routes`, hoặc đổi `strategy`. Mỗi `name` phải duy nhất. Đường dẫn API được cố định theo provider, không cần tự điền base URL.

Ví dụ chuyển sang model chính + dự phòng:

```json
"strategy": "priority"
```

Sau khi sửa key/config, áp dụng riêng extension:

```sh
docker compose --env-file .env -f warehouse_agents/compose.yml up -d --force-recreate
```

Đổi mã Python router mới cần build image; đổi JSON/key chỉ cần recreate. Restart thường không cập nhật biến môi trường mới từ `.env`. Recreate cũng reset con trỏ và cooldown trong RAM.

## 6. Lỗi, timeout và theo dõi

| Thiết lập hiện tại | Giá trị |
| --- | --- |
| Timeout mỗi slot | 20 giây |
| Deadline tổng mỗi lượt LLM | 60 giây |
| Cooldown slot lỗi | 30 giây, hoặc theo `Retry-After` của provider nếu dài hơn (tối đa 1 giờ) |
| Lỗi được chuyển route | Mọi HTTP 4xx/5xx, network/timeout và output không dùng được |
| Hết route/deadline | Báo `RouterUnavailable`, không bịa kết quả |

Ví dụ Groq hết quota ngày trả 429 với `Retry-After: 171`, nên slot đó nghỉ 171 giây thay vì bị gọi lại sau 30 giây. Deadline tổng có thể hết trước khi thử hết mọi slot. 400/401/403 vẫn cần sửa cấu hình/quyền; fallback không sửa nguyên nhân.

Kết quả agent có `routing` (provider/model/slot được chọn, độ trễ, các attempts) và `steps` (từng lượt LLM: model, fallback, token, reasoning nếu model trả về, và từng tool call với input, output, thời gian). Desk hiện model dưới mỗi câu trả lời và cho mở từng bước. Log không chứa key hoặc raw response body; hiện **chưa có dashboard quản trị router riêng**. Token usage là phần response thành công; request lỗi có thể vẫn phát sinh phí ngoài số usage đó.

## 7. Giới hạn và model trả phí

Route có `price` (USD / 1 triệu token) trong `router.json` là model trả phí, hiện chỉ có Haiku. API quyết định ai
được gọi và bao nhiêu lần ([`app/usage.py`](../app/usage.py)), đếm từ `meta.agent_run` theo ngày UTC:

| Người dùng | Model | Giới hạn mặc định |
|---|---|---|
| Owner (`AGENT_OWNER_EMAILS`, và `local` khi chạy máy) | Tất cả | Không giới hạn |
| Đã đăng nhập | Groq, Gemma; Haiku khi còn lượt | 20 câu/ngày, 4 lệnh/phút, mỗi lúc một lệnh; Haiku 5 câu/ngày |
| Tất cả cộng lại | Haiku | Ngân sách $1/ngày, hết thì Haiku tắt với người không phải owner |
| Chưa đăng nhập (Supabase, theo IP) | Chỉ model miễn phí | 5 câu/ngày mỗi IP, tổng 200 câu/ngày; không có lịch sử, không có memory |

Vượt giới hạn trả về 429 kèm lý do. Ai không được dùng model trả phí mà chọn Auto thì chạy `auto-free`:
router vẫn đổi vòng giữa các route miễn phí nhưng không bao giờ rơi xuống Haiku. Model picker làm mờ Haiku
kèm lý do, thanh Desk hiện số câu còn lại hôm nay.

## 8. Dữ liệu đi đâu và ảnh hưởng phần nào?

Khi chuyển provider, toàn bộ hội thoại đang dùng, tool schema và bằng chứng tool có thể được gửi sang provider kế tiếp. Chỉ cấu hình provider được phép nhận dữ liệu đó. Router không tự thực thi tool; validator/tool runner vẫn giữ quyền chỉ đọc và danh sách cho phép.

| Phần | Có dùng router này? |
| --- | --- |
| Analyst / Operations (8021/8022) | **Có** |
| MCP `ask_analyst` / `ask_operations` (8020) | **Có**, qua hai agent |
| MCP anomaly/drift trực tiếp | **Không cần LLM** |
| Dự báo hai CatBoost / Isolation Forest | **Không** |
| Desk `@trade` / `@sre` qua `/v1/agent/command` | **Có** |
| Desk plain text (đi tới Analyst qua `/v1/agent/command`) | **Có** |

[Quay lại tổng quan và tiến độ](current_progress.md) · [Cách chạy và kiểm chứng agent](agent_control.md)
