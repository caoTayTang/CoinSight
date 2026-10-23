# CoinSight là gì

CoinSight là một kho dữ liệu crypto kèm agent AI chỉ đọc. Agent trả lời câu hỏi về thị trường và về pipeline chỉ
từ bằng chứng trong kho; bộ eval dùng chính kho dữ liệu làm đáp án để chấm agent. Đây là hệ thống nghiên cứu, không
phải công cụ giao dịch.

```text
Binance (archive + WebSocket) ─► Kafka / Spark / Airflow ─► PostgreSQL: staging · dw · mart · meta
                                                                │
                                   tool chỉ đọc: coverage, quality, lineage, đối soát, giá, dự báo
                                                                │
                                   agent Trade / SRE (LangGraph + router LLM) ─► Desk trên web
```

| Phần | Làm gì | Đọc ở |
|---|---|---|
| Nền tảng dữ liệu | Nến Binance vào kho, kiểm chất lượng, lineage, marts | II |
| Agent AI | Chọn tool, đọc bằng chứng, trả lời có nguồn; không sửa kho | III |
| Mô hình dự báo | Dự báo BTC giờ tới (đóng băng), phát hiện bất thường, ledger chấm dự báo | IV |
| Vận hành | Home server, đăng nhập, CI/CD, tracing, admin | V |

## Đọc tài liệu theo thứ tự nào

| Bạn muốn | Đọc |
|---|---|
| Chạy thử trên máy | I.2 Chạy hệ thống, rồi I.3 Dùng Desk |
| Hiểu agent được kiểm chứng ra sao | III.6 Đánh giá agent |
| Hiểu dữ liệu đi đâu | II.1 Luồng dữ liệu, II.2 Schema kho |
| Gắn một model dự báo mới | IV.3 Gắn một mô hình mới |
| Đưa lên server | V.1 Home server, V.2 Đăng nhập, V.3 CI/CD |

Mỗi chủ đề có đúng một trang; trang khác chỉ dẫn link tới đó. Số liệu eval và dự báo chỉ nằm ở trang của chúng.
Ghi chú nghiên cứu cũ nằm trong mục **Lưu trữ** cuối mục lục; chúng có thể không còn đúng với code hiện tại.
