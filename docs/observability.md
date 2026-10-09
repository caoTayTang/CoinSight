# Theo dõi xử lý với Jaeger

Mở http://localhost:16686, chọn service rồi tìm trace. Mỗi trace nối các lần xử
lý liên quan; mỗi span ghi một bước và thời gian của bước đó.
Cách khởi động service nằm tại [Chạy hệ thống](running_system.md).

## 1. Trợ lý và API

```text
assistant.request
├── bedrock.converse
└── assistant.tool.<tên công cụ>
    └── warehouse.query
```

Lỗi đánh dấu span ERROR. Có mã lỗi nhà cung cấp, duration và token nhà cung cấp trả về.
Dữ liệu thiếu/cũ là kết quả công cụ, không tự biến thành lỗi thực thi.
Thông tin xuất trace không bao gồm prompt, câu trả lời, SQL, credentials,
đầu vào công cụ hay nguyên văn exception nhà cung cấp.

`trace.trace_id` và `X-Trace-ID` là ID OpenTelemetry 32 ký tự hex khi bật tracing;
nếu chưa bật, chat dùng UUID của request. ID nguồn dữ liệu trong API có thể khác;
span công cụ liên kết nó bằng `data.trace_id`.

Phạm vi hiện có: chat, nhà cung cấp, công cụ và helper truy vấn. Chưa phủ mọi HTTP route,
browser hoặc session hội thoại. Export bất đồng bộ; Jaeger lỗi không được chặn API.

## 2. luồng xử lý dữ liệu

| Service / span | Ghi gì và liên kết thế nào |
| --- | --- |
| `coinsight-producer` / `kafka.publish` | Pair, event ID, topic/partition/offset đã xác nhận; W3C context trong headers |
| `coinsight-spark` / `spark.candles.commit` | Nhận event → ghi DB; tối đa 128 link context upstream mỗi micro-batch, có số link bị bỏ |
| `spark.metrics.commit` | Thời gian ghi aggregate; chưa ánh xạ đủ mọi event vào metric |
| `spark.query.progress` | theo lô ID, số dòng, throughput, watermark và thời gian trigger; đây là thuộc tính trace, chưa phải kho metrics |
| `coinsight-airflow` | DAG/run/task/try, theo lô ID, số dòng, trạng thái; context qua `_trace_context` trong XCom |

Retry Airflow có span riêng; downstream nối với lần upstream thành công.
Message Kafka cũ không có headers vẫn xử lý được nhưng không có link upstream.
Không tạo trace ngược cho job đã chạy trước khi bật instrumentation.

## 3. Đã kiểm chứng tới đâu?

Unit tests dùng exporter trong bộ nhớ và nhà cung cấp giả lập. Đã gửi trace kiểm
thử tới Jaeger và có một lượt Bedrock thật gọi `get_snapshot` thành công với
haiku tại `us-east-1`. ResourceNotFound trước đó chưa xác định nguyên nhân.
Instrumentation Kafka/Spark/Airflow đã có mã nguồn; cần kiểm tra toàn luồng thật.

Jaeger local dùng RAM: restart sẽ mất trace. Chưa có lưu trữ lâu dài, thời hạn lưu,
alerts, tính chi phí hoặc nối PostgreSQL NOTIFY tới browser trong cùng trace.
Danh sách nghiệm thu các phần này được giữ tại [Tiến độ](product_readiness.md).
