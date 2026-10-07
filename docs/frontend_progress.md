# CoinSight frontend — tiến độ

UI hiện tại: Market chỉ hiển thị giá nến phút, change/volume 15 phút, daily close,
chart 30D/90D và tín hiệu. Hai tab Chart/Signal; diagnostics nằm trong Operations.
Chat dùng câu chữ ngắn, model ID và trace nằm trong phần mở rộng Request details.
Các ghi chú layout phía dưới là lịch sử triển khai, không phải toàn bộ UI hiện tại.

Đây là tiến độ triển khai kỹ thuật, không phải xác nhận sản phẩm hoàn chỉnh.
Ưu tiên và tiêu chí nghiệm thu nằm ở [product_readiness.md](product_readiness.md).
Market overview và Data & model operations hiện là hai ngữ cảnh điều hướng;
chưa có phân quyền admin/user. Assistant chưa có memory, skill framework hoặc
trace store bền vững. Trace request/tool/provider hiện có trong Jaeger local,
response và Docker log; Jaeger đang dùng bộ nhớ tạm, mất trace khi restart.

Trang React/Vite được build từ `frontend/src/` tại `http://localhost:3000`. File
`frontend/code.html` là bản Stitch gốc để đối chiếu thiết kế, không phải trang
được deploy.

## Đã làm

- [x] Workspace mới: tìm coin bên trái; các view Price history, Live market,
      Prediction ở giữa; Assistant và Data & evidence ở cột phải.
- [x] Chat có không gian riêng và câu hỏi gợi ý để điền vào ô nhập trước khi gửi.
- [x] Kiểm tra trình duyệt desktop 1512px và mobile 390px: tìm coin, chuyển view,
      chuyển evidence/chat, chọn gợi ý, mở rộng/Escape; không tràn ngang hay lỗi JS.

- [x] Bố cục ba cột, màu, Plus Jakarta Sans và JetBrains Mono theo bản Stitch.
- [x] Layout responsive: danh sách coin cuộn ngang và panel xếp dọc trên điện thoại.
- [x] Danh sách coin, giá đóng ngày và chart lấy từ warehouse qua FastAPI.
- [x] Live 15 phút và metric Spark 7 ngày, dự đoán ngày kế tiếp, đánh giá model lấy từ API v1.
- [x] Kiểm tra local: Spark live ghi nến và metric, API trả đủ 15/15 nến cho BTC sau khi khởi động lại ngày 06/10/2026.
- [x] Vùng dự đoán hiển thị xác suất tăng khi có model được chấp nhận; nếu
      không có thì hiện lý do. Model hiện không tạo đường giá dự báo.
- [x] Evidence audit hiển thị batch, nguồn, độ mới, coverage và model status thật.
- [x] Chat gửi câu hỏi đến `/v1/agent/chat`, render Markdown, có chế độ mở rộng,
      hiển thị model ID của mỗi câu trả lời và báo lỗi nếu Bedrock chưa sẵn sàng.
- [x] Giá trị thiếu/stale/unavailable được hiển thị, không thay bằng số liệu mẫu.
- [x] Nginx phục vụ frontend và proxy `/api` đến FastAPI trong Docker Compose.
- [x] React dùng chung card, badge, evidence và chart; hai khu vực Batch/Live có nguồn và lịch cập nhật riêng.
- [x] Live nhận WebSocket; PostgreSQL NOTIFY sau Spark commit, FastAPI gửi snapshot và reconnect khi mất mạng.
- [x] CI build image frontend, kiểm trang và kiểm proxy API; push `main` publish GHCR image.

## Cần hoàn thành trước khi công bố ra domain

- [ ] Kiểm chứng Spark ở chế độ `live` chạy ổn định nhiều ngày; producer chạy
      một mình không đủ. Compose hiện tự restart Spark khi process thoát.
- [ ] Có model được chấp nhận hoặc giữ trạng thái “Not published”. Hiện model
      candidate gần nhất bị từ chối vì không thắng baseline.
- [x] Haiku 4.5 đã trả lời một câu hỏi thật qua API và gọi get_snapshot BTC;
      trace được kiểm tra trong Jaeger. Lỗi ResourceNotFoundException cũ chưa rõ
      nguyên nhân; chưa kiểm chứng độ ổn định hoặc toàn bộ tool.
- [ ] Bổ sung xác thực/rate limit và chính sách public API trước khi mở API ra Internet.
- [ ] Tự host font nếu cần bảo đảm giao diện hoạt động khi không truy cập được
      Google Fonts; CSS hiện được phục vụ local, font tải từ Google.
- [ ] Quyết định host cho FastAPI/PostgreSQL/Kafka/Spark và public API origin.
- [ ] Xác nhận workflow CI xanh trên GitHub sau khi commit/push các thay đổi.
- [ ] Cấu hình Wrangler Workers Static Assets, domain và CI deploy sau khi API
      origin, secret và môi trường production được chốt.
- [ ] Kiểm tra responsive bằng thiết bị thật và kiểm tra accessibility chi tiết.

## Kiểm tra nhanh

```bash
docker compose up --build -d frontend
curl -i http://localhost:3000/api/health
curl -i http://localhost:3000/api/v1/data-status
npm --prefix frontend run build
```

Mở `http://localhost:3000`. Khi chọn coin, Batch đổi snapshot/chart/evidence;
Live mở WebSocket cho coin đó và đổi theo nến phút được Spark commit. Khi API
trả `unavailable`, UI ghi đúng trạng thái đó.
