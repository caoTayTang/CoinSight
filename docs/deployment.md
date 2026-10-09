# Triển khai và CI/CD

## 1. Hiện có

Workflow GitHub Actions kiểm Python với PostgreSQL, cấu hình Compose, giao diện
và build image API/frontend/pipeline/Spark/Airflow. Tập kiểm tra giao diện trên runner
cần `npm ci`, độc lập với dependencies bên trong Docker image.
Push lên `main` publish image theo SHA và `latest` tới GHCR.
Chưa có máy chủ production hoặc DNS được cấu hình từ workspace này.

## 2. Kiến trúc triển khai dự kiến

Cần máy Linux chạy PostgreSQL, Kafka, Spark, API và Airflow nếu bật lịch.
Nginx phục vụ React và proxy REST/WebSocket tới API. Cloudflare Worker không
thay thế các dịch vụ dữ liệu chạy dài hạn.
Tên `coinsight.kaiosthefox.dpdns.org` mới là ứng viên, chưa xác nhận DNS/hosting.

## 3. Điều kiện để bật CD

Cần chốt máy chủ/SSH, DNS, HTTPS, quản lý secrets và backup. Deploy image bằng SHA,
chạy migration rồi kiểm `/ready`, `data-status`, `live-summary` và trạng thái DAG.
Có phương án rollback schema/image trước khi tự động deploy.
Giữ DB/Kafka nội bộ; không mở giao diện quản trị local ra Internet.

Giao diện image dùng build context repo gốc để lấy Markdown; root `.dockerignore`
giới hạn nội dung được đóng gói. Sửa tài liệu phải build lại image để cập nhật web.
Cách chạy local ở [Chạy hệ thống](running_system.md); tiêu chí vận hành ở
[Tiến độ](product_readiness.md).
