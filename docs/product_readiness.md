# Tiến độ và công việc còn thiếu

Bản nghiên cứu chạy local; chưa đủ điều kiện vận hành thực tế. Build/test chứng
minh những đường mã nguồn được kiểm tra, không chứng minh giá trị dự báo hoặc khả
năng ra quyết định. Không có phần trăm hoàn thành khi chưa thống nhất phạm vi.

## 1. Đã có

| Phần | Phạm vi |
| --- | --- |
| Dữ liệu | theo lô ZIP, staging, quality, warehouse/mart và lineage file nguồn |
| Dữ liệu trực tiếp | Binance → Kafka → Spark → DB; REST bù nến và checkpoint |
| API / giao diện | API, WebSocket, chart thật, trang thị trường/vận hành và trang tài liệu |
| Mô hình ngày | Logistic hồi quy, đánh giá phương pháp đối chiếu, điều kiện công bố và tệp mô hình |
| Trợ lý | Bedrock chọn công cụ chỉ đọc; Markdown và thông tin chẩn đoán |
| Theo dõi | OpenTelemetry/Jaeger; phạm vi cụ thể ở trang Theo dõi |
| CI | Tập kiểm tra, build image và publish GHCR; CD tới server chưa có |
| Dự báo giờ | Giao ước và lựa chọn BTC XGBoost; chưa có dataset/training/API giờ |

Các workspace Market/Operations chưa có phân quyền. UI không chứng minh
usability; agent chưa có trí nhớ giữa các request.

## 2. Dữ liệu và mô hình — ưu tiên tiếp theo

- [ ] Chốt phạm vi nạp bù lịch sử BTC: đề xuất từ 2024; cập nhật giao ước trước khi đổi phân chia.
- [ ] Nạp bù lịch sử, kiểm gap/trùng và lưu bản chụp dữ liệu bất biến cùng checksum.
- [ ] Xây tập dữ liệu và kiểm tra label/feature không nhìn tương lai, đặc biệt ở ranh phân chia.
- [ ] Huấn luyện hai phương pháp đối chiếu và XGBoost, lưu kết quả cả khi mô hình bị từ chối.
- [ ] Đánh giá theo coin/giai đoạn; tập kiểm tra cuối giữ riêng không dùng để chọn candidate.
- [ ] Cấp nến giờ mới cho suy luận; kiểm tra freshness/gap trước khi dự báo.
- [ ] Lưu registry/artifact bất biến và đủ theo lô nguồn của mọi đặc trưng.
- [ ] API và UI giờ so dự báo với giá thực tế; không gọi return là xác suất.

**Rủi ro daily classifier hiện tại:** tập kiểm tra score đang tham gia điều kiện công bố;
lặp nhiều candidate sẽ làm tập kiểm tra trở thành tập chọn mô hình. Phiên bản tệp mô hình
có thể bị ghi đè theo feature/cutoff; tệp mô hình và đăng ký DB chưa atomic.
Lineage cần kiểm đủ theo lô của cửa sổ trượt features. Tất cả cần audit trước khi
khẳng định có mô hình đáng tin.

## 3. luồng xử lý và vận hành

- [ ] Nạp cùng archive hai lần: khóa không trùng, số dòng và audit đúng.
- [ ] Restart producer/Spark, gây mất kết nối nguồn: đo phút thiếu/trùng và phục hồi.
- [ ] Kiểm lịch Airflow, retry/backfill và quan hệ giữa ingestion với suy luận.
- [ ] Đo độ phủ thực của cửa sổ aggregate; số event không chứng minh đủ bảy ngày.
- [ ] Kiểm tra traces producer → Spark và Airflow bằng dữ liệu thật.
- [ ] Metrics và cảnh báo độ mới, khoảng thiếu, Kafka lag, task lỗi, nhà cung cấp timeout;
  Gây từng lỗi rồi chứng minh cảnh báo bật và được giải quyết.
- [ ] Jaeger có lưu trữ/retention phù hợp và kiểm soát truy cập.
- [ ] Nginx tự xử lý API container đổi địa chỉ; kiểm lại mà không restart giao diện.

## 4. Trợ lý

- [ ] Công bố capabilities từ API, tránh UI/model/chat lệch danh sách coin.
- [ ] Dẫn nguồn cho từng kết luận bằng số liệu/timestamp và lineage/trace liên quan.
- [ ] Bộ nhớ session có giới hạn, phạm vi asset, reset và cách ly giữa người dùng.
- [ ] Các kỹ năng phân tích có input/output, kiểm tra và cách xử lý lỗi rõ ràng.
- [ ] Bộ eval: số liệu có căn cứ, chọn đúng coin/tool, từ chối dữ liệu cũ/thiếu,
  Lỗi nhà cung cấp và prompt injection trong nội dung công cụ.
- [ ] Timeout, huỷ request, retry có giới hạn, hạn mức token/chi phí và cảnh báo.
- [ ] Chỉ thêm nhiều agent khi đo được lợi ích so với một agent có công cụ tốt.

**Bedrock:** một lượt thật thành công chưa chứng minh ổn định. Lỗi ResourceNotFound
trước đó chưa tái hiện được; chưa thể khẳng định đã giải quyết nguyên nhân.

## 5. Sản phẩm và triển khai

- [ ] Hai người mới thử tác vụ từ chọn coin tới hiểu timestamp/giới hạn mô hình.
- [ ] So sánh coin cùng thời kỳ và đủ độ phủ; không xếp hạng cửa sổ lệch nhau.
- [ ] Thống nhất câu hỏi hỗ trợ quyết định và tiêu chí thành công với Dương/rubric.
- [ ] Dọn CSS tích lũy, xác định token và trách nhiệm component.
- [ ] Auth/phân quyền, rate limits, secrets và giới hạn concurrency.
- [ ] Load tập kiểm tra WebSocket: thiết kế hiện có một PostgreSQL listener mỗi client.
- [ ] Kiểm backup/restore, migration DB mới/cũ, rollback và CD tới server/domain.

## 6. Bằng chứng kiểm tra

Ngày 07/10/2026: 53 Python tests pass với PostgreSQL, không skip; giao diện build
và API/frontend Docker build chạy local. Bản docs 09/10 có thêm ba tập kiểm tra điều hướng,
tổng 10 giao diện tests. CI từng thiếu `npm ci` trên runner; đã sửa trong `65235b6`.
Trạng thái CI mới nhất phải xem trên PR, không coi bản ghi này là kết quả mọi ghi thành công.
Ảnh/smoke tập kiểm tra chưa thay cho thử nghiệm người dùng, recovery hoặc đánh giá mô hình.

Lệnh thao tác nằm ở [Chạy hệ thống](running_system.md). Bài toán/model được định
nghĩa tại hai giao ước ngày và giờ; trang này chỉ giữ tiến độ và nghiệm thu.
