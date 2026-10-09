# CoinSight — Kho dữ liệu và hỗ trợ quyết định

CoinSight lấy nến Spot Binance, lưu lịch sử và dữ liệu trực tiếp vào PostgreSQL,
phục vụ bảng theo dõi thị trường, mô hình thử nghiệm và trợ lý đọc dữ liệu.
**Trạng thái: bản nghiên cứu, chưa đủ điều kiện vận hành thực tế.**

## Đọc tài liệu

Mở **http://localhost:3000/docs/**. Mỗi chủ đề có một trang chính:

| Muốn tìm gì? | Trang |
| --- | --- |
| Cài đặt, lệnh chạy, DataGrip, lỗi thường gặp | [Chạy hệ thống](docs/running_system.md) |
| Dữ liệu đi qua những bước nào, code ở đâu | [Luồng dữ liệu](docs/data_flow.md) |
| Bảng, khóa, sơ đồ quan hệ, mart OLAP | [Thiết kế kho dữ liệu](docs/dw_design.md) |
| Định dạng sự kiện và phản hồi API | [Giao ước dữ liệu](docs/data_contracts_v1.md) |
| Mô hình ngày hiện tại | [Giao ước dự đoán hướng ngày](docs/dss_contract_v1.md) |
| Bài toán giờ đã chốt, chuẩn bị triển khai | [Giao ước dự báo giờ](docs/hourly_forecast_contract.md) |
| So sánh các họ mô hình dự kiến | [Nghiên cứu mô hình của Dương](docs/forecasting_design.md) |
| Truy vết lỗi và thời gian xử lý | [Theo dõi với Jaeger](docs/observability.md) |
| Đã làm, còn thiếu, tiêu chí nghiệm thu | [Tiến độ và công việc](docs/product_readiness.md) |
| Máy chủ, tên miền, CI/CD | [Triển khai](docs/deployment.md) |
| Quy tắc trình bày giao diện | [Thiết kế giao diện](frontend/DESIGN.md) |

## Chạy nhanh

```bash
cp .env.example .env  # lần đầu; giữ file .env đang có nếu đã cấu hình
docker compose up --build -d
```

Mở http://localhost:3000 cho bảng theo dõi hoặc http://localhost:3000/docs/
cho tài liệu. Chạy nhanh chưa tự nạp toàn bộ lịch sử hay huấn luyện mô hình;
các lệnh này được hướng dẫn tại trang Chạy hệ thống.

## Cấu trúc và trách nhiệm file

```text
CoinSight/
├── README.md                            Hướng dẫn cài đặt và sử dụng
├── pipeline/
│   ├── settings.yaml                    Coin, interval, lịch và ngưỡng xử lý
│   ├── settings.py                      Đọc YAML và biến môi trường
│   ├── telemetry.py                     Trace producer, Spark và Airflow task
│   ├── batch/
│   │   ├── binance_archive_format.py    Tên archive và định dạng CSV Binance
│   │   ├── binance_archive_downloader.py Tải ZIP, kiểm checksum
│   │   ├── staging_writer.py           Ghi archive vào staging và manifest
│   │   ├── ingest_binance_history.py   Điều phối ingest lịch sử Binance
│   │   ├── quality_checks.py           Rule kiểm tra dữ liệu batch
│   │   └── warehouse_loader.py         Nạp fact/dimension, refresh mart
│   ├── stream/
│   │   ├── kaggle_replay_producer.py    Replay CSV Kaggle vào Kafka
│   │   ├── binance_live_client.py       Đọc Binance REST/WebSocket
│   │   ├── kafka_publisher.py           Gửi Kafka, lưu tiến độ theo coin
│   │   ├── spark_stream_processor.py   Lọc event, tính metric bằng Spark
│   │   └── stream_sink_writer.py       Ghi nến và metric vào PostgreSQL
│   ├── decision/
│   │   ├── feature_builder.py          Đọc warehouse, tạo feature/label
│   │   └── direction_model.py          Train, đánh giá, dự đoán hướng giá
│   ├── Dockerfile                       Image Python cho batch và producer
│   ├── Dockerfile.spark                 Image Spark
│   └── requirements.txt                Thư viện Python cho pipeline
├── airflow/
│   ├── dags/coinsight_warehouse.py     Lịch ingest và load warehouse
│   ├── dags/coinsight_dss.py           Daily classifier: train thứ Hai, predict mỗi ngày
│   ├── create_metadata_db.py           Tạo metadata DB cho Airflow
│   ├── Dockerfile                       Image Airflow
│   ├── requirements-tracing.txt         Phiên bản tracing tương thích image Airflow
│   └── requirements.txt                Thư viện Airflow cần thêm
├── app/
│   ├── api.py                           Endpoint FastAPI
│   ├── api_schemas.py                   Schema request/response Pydantic
│   ├── chat_agent.py                    Bedrock chat và tool đọc dữ liệu
│   ├── live_stream.py                   LISTEN PostgreSQL và đẩy WebSocket
│   ├── telemetry.py                     Trace assistant, Bedrock và tool/query
│   ├── static/dashboard.html            Trang dashboard
│   ├── static/dashboard.css             Kiểu giao diện
│   ├── static/dashboard.js              Gọi API, cập nhật giao diện
│   ├── Dockerfile                       Image API
│   └── requirements.txt                Thư viện API
├── frontend/
│   ├── index.html                       React mount point
│   ├── src/App.jsx                      Workspace Market/Operations và chat
│   ├── src/MarketOverview.jsx           Giá, biến động, chart 30D/90D, trạng thái tín hiệu
│   ├── src/readiness.js                 Kiểm freshness/coverage và hiệu lực prediction
│   ├── src/readiness.test.js            Test dữ liệu cũ, thiếu và prediction hết hạn
│   ├── src/components.jsx               Card, badge, chart, chat dùng lại
│   ├── src/useLiveStream.js              WebSocket và reconnect theo coin
│   ├── src/format.js                     API client và format giá/thời gian
│   ├── styles.css                       Style responsive theo thiết kế Stitch
│   ├── package.json / package-lock.json React + Vite cố định phiên bản
│   ├── nginx.conf                       Proxy REST + WebSocket tới FastAPI
│   ├── code.html                        Mockup Stitch gốc để đối chiếu
│   ├── DESIGN.md                        Quy tắc layout, màu sắc và typography
│   ├── screen.png                       Ảnh tham chiếu giao diện
│   └── Dockerfile                       Build Vite rồi phục vụ bằng Nginx
├── postgres/
│   ├── init/01_staging_meta.sql         Staging, ETL log, lineage, DQ
│   ├── init/02_dw_schema.sql            Dimension, fact và view nền
│   ├── init/03_seed.sql                 Coin tham chiếu
│   ├── init/04_marts.sql                View OLAP
│   ├── migrations/001_contracts_v1.sql Nâng DB cũ lên contract v1
│   ├── migrations/002_decision_pipeline.sql  Bảng DSS
│   ├── migrations/003_live_notifications.sql Thông báo khi live commit
│   └── queries/olap_examples.sql       Truy vấn OLAP mẫu
├── tests/
│   ├── batch/test_ingest_binance_history.py  Test ZIP, checksum, parse nến
│   ├── batch/test_warehouse_loader.py        Test staging, DQ, fact, mart
│   ├── stream/test_kaggle_replay_producer.py  Test đọc CSV replay
│   ├── stream/test_binance_live_client.py     Test nến live và reconnect
│   ├── decision/test_feature_builder.py       Test label theo ngày UTC
│   ├── app/test_dss_contract.py                Test API DSS publish/reject
│   ├── app/test_api.py                        Test health và API response
│   ├── app/test_chat_agent.py                 Test tool agent được phép gọi
│   ├── app/test_telemetry.py                  Test trace API/assistant bằng exporter giả lập
│   ├── observability/test_pipeline_tracing.py Test propagation và spans của pipeline
│   └── app/test_live_stream.py                Test WebSocket push
├── docs/
│   ├── running_system.md               Cài đặt, chạy, kiểm tra và xử lý lỗi
│   ├── data_flow.md                    Luồng dữ liệu toàn hệ thống và vị trí code từng bước
│   ├── data_warehouse.md               Trang cũ, đã gộp vào dw_design.md
│   ├── dw_design.md                    Thiết kế schema và ETL chi tiết
│   ├── data_contracts_v1.md           Contract, lineage, chất lượng
│   ├── dss_contract_v1.md              Handoff model, bảng output và API cho Dương
│   ├── forecasting_design.md           Proposal hourly forecasting của Dương, chưa triển khai
│   ├── hourly_forecast_contract.md     Contract giờ đã chốt; BTC XGBoost là model đầu tiên
│   ├── product_readiness.md            Critique, backlog và tiêu chí nghiệm thu
│   ├── observability.md                Jaeger, phạm vi tracing và giới hạn
│   ├── deployment.md                  Hướng dẫn triển khai
│   ├── frontend_progress.md           Trang cũ, đã gộp vào product_readiness.md
│   ├── DW_Review_1_....pdf            Slide môn học tham khảo
│   ├── diagrams/EERD.pdf              Sơ đồ thực thể
│   └── diagrams/Relation-schema.pdf   Sơ đồ quan hệ
├── scripts/generate_diagrams.py        Sinh sơ đồ DW
├── scripts/demo_direction_model.py     Thử classifier với dữ liệu tổng hợp
├── data/sample.csv                     CSV mẫu; data/raw/ là cache local
├── .env.example                        Mẫu cấu hình triển khai
├── .gitignore                           Bỏ qua cache, môi trường và dữ liệu local
├── .github/workflows/ci.yml           Test, build và publish image
├── docker-compose.yml                  Container, volume và network
└── Makefile                            Lệnh tắt để chạy project
```

Markdown là nguồn duy nhất của trang tài liệu. Sau khi sửa, build lại frontend:

```bash
docker compose up -d --no-deps --build frontend
```

Khi phát triển dùng `npm --prefix frontend run dev`; tài liệu tự tải lại khi sửa.
Docker build frontend dùng context repo gốc: `docker build -f frontend/Dockerfile .`.
