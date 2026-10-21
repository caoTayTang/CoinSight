# Lộ trình hoàn thiện CoinSight

CoinSight là bản nghiên cứu. Ưu tiên chứng minh một luồng chạy ổn định trước khi thêm tính năng.

## Luồng chính cần hoàn thiện

```text
Lịch sử Binance
  → staging
  → kiểm tra chất lượng
  → fact và mart trong warehouse
  → API
  → dashboard và trang tài liệu
```

Dự án đủ hoàn thiện cho phạm vi này khi người mới có thể clone repo, chạy Docker
Compose, nạp mẫu Binance, xem chất lượng dữ liệu, mở dashboard/tài liệu và chạy test.

## Giai đoạn 0 — Chuẩn bị PR và demo

- [x] Trang tài liệu tại `/docs/`.
- [x] CI cài dependency frontend trước khi chạy test.
- [x] Frontend test và build thành công local.
- [x] Python test thành công local qua `uv run`.
- [x] Bỏ qua PDF tham khảo local ngoài `docs/diagrams/`.
- [x] Thêm lộ trình và kịch bản demo.
- [ ] Push nhánh và xác nhận CI trên GitHub.

## Giai đoạn 1 — Kiểm chứng kho dữ liệu

- [x] Tải archive Binance và cache local.
- [x] Staging và warehouse loader.
- [x] Kiểm tra chất lượng và bảng truy vết nguồn.
- [x] OLAP marts.
- [x] Báo cáo nến thiếu/trùng theo coin và interval.
- [x] Báo cáo số dòng staging → fact theo lần nạp.
- [x] Kiểm chứng nạp lại cùng archive không thay đổi fact.
- [x] Truy fact mới/thay đổi tới đúng archive và checksum bằng truy vấn demo.

Cách triển khai và lệnh kiểm chứng: [Kiểm chứng kho dữ liệu](warehouse_proof.md).

Bằng chứng local: 55 Python test pass với PostgreSQL, không skip; 11 frontend test
pass và build thành công. Nạp ZIP BTC giờ `BTCUSDT-1h-2026-09-12.zip` hai lần: đọc 24
dòng mỗi lần, không thay đổi fact đã có và giữ nguyên SHA-256 của 21.700 fact ngày/giờ.
Truy vết archive chính xác cho dòng mới được kiểm trong database tạm. Fact trước
migration có lineage archive `null`, không được gán nguồn bằng suy đoán.

## Giai đoạn 2 — Kiểm chứng dashboard

- [x] Dashboard thị trường.
- [x] Thẻ bằng chứng trong Operations.
- [x] Kiểm tra độ mới và độ sẵn sàng dữ liệu.
- [x] Liên kết trang tài liệu từ ứng dụng.
- [x] Biểu đồ nến live 1 phút riêng để xem trạng thái hiện tại.
- [ ] Cải thiện trạng thái rỗng/lỗi khi database mới chưa có dữ liệu.
- [ ] Tóm tắt chất lượng lần nạp mới nhất rõ hơn.

## Giai đoạn 3 — Kiểm chứng mô hình

- [x] Mẫu mô hình dự đoán hướng ngày.
- [x] Giao ước DSS cho dự đoán ngày.
- [x] Giao ước dự báo giờ.
- [ ] Chốt khoảng dữ liệu BTC giờ.
- [ ] Tạo feature/label giờ và kiểm tra không nhìn tương lai.
- [ ] Huấn luyện mô hình đối chiếu trước XGBoost.
- [ ] Huấn luyện candidate XGBoost BTC giờ.
- [ ] Lưu đánh giá cả mô hình được chấp nhận và bị từ chối.
- [ ] Cấp dự báo giờ mới nhất qua API/giao diện.

## Giai đoạn 4 — Kiểm chứng vận hành

- [x] Docker Compose chạy local.
- [x] Python/frontend test trong CI.
- [x] Build Docker image trong CI.
- [ ] Kiểm backup và restore.
- [ ] Restart producer/Spark, kiểm nến live thiếu/trùng và khả năng phục hồi.
- [ ] Dependency Airflow giữa nạp warehouse và dự đoán DSS.
- [ ] Triển khai thực tế, quản lý secrets, auth và rate limit.

## Chưa làm lúc này

Chỉ xem xét sau khi luồng chính đã ổn định:

- chat nhiều agent;
- dự báo nhiều coin;
- cảnh báo nâng cao;
- auth và kiểm soát chi phí cho môi trường thực tế;
- tối ưu Spark quy mô lớn;
- thiết kế lại UI ngoài các cải thiện về rõ ràng và chính xác.
