# Giao ước dự đoán hướng giá theo ngày

Đây là bài toán **đã có implementation**, độc lập với
[giao ước dự báo giá theo giờ](hourly_forecast_contract.md).
Lệnh chạy ở [Chạy hệ thống](running_system.md); lịch ở [Luồng dữ liệu](data_flow.md).

## 1. Câu hỏi

Sau khi nến ngày UTC D đã đóng và được nạp, xác suất giá đóng ngày D+1 cao hơn
ngày D là bao nhiêu? Dùng BTC/ETH/SOL, cặp Spot USDT. Bằng hoặc thấp hơn có nhãn 0,
cao hơn nhãn 1. `as_of_date=D`, `target_date=D+1`, `probability_up` trong [0,1].
Đây là xác suất hướng, không phải giá dự báo, return hay tín hiệu đặt lệnh.

## 2. Đầu vào và nhãn

Nguồn `dw.fact_ohlcv_daily`, chỉ Binance. Dùng `dw.fact_ohlcv_hourly` để tính
`hourly_range` từ đủ 24 giờ của chính ngày D.
[feature_builder.py](../pipeline/decision/feature_builder.py) tạo:
`return_1d`, `return_7d`, `range_pct`, `volume_change`, `hourly_range` và `symbol`.
`next_close` chỉ tạo nhãn train, không được làm đặc trưng dự đoán.
Nhãn chỉ hợp lệ khi ngày kế tiếp đúng D+1; không nhảy qua ngày thiếu.

## 3. Huấn luyện và công bố hiện tại

[direction_model.py](../pipeline/decision/direction_model.py) dùng logistic regression
chung ba coin. Giữ 30 ngày kiểm định và 30 ngày kiểm tra cuối theo thứ tự thời gian.
Baseline là tỷ lệ ngày tăng trong tập train. Brier score thấp hơn là tốt hơn.

Code hiện chỉ công bố khi Brier thấp hơn baseline trên cả hai tập. Đây là hành vi
hiện có, không phải thiết kế đánh giá hoàn hảo: lặp chọn candidate bằng test score
làm test mất tính độc lập. Audit ranh nhãn, artifact và lineage còn trong
[Tiến độ](product_readiness.md#2-dữ-liệu-và-mô-hình--ưu-tiên-tiếp-theo).

## 4. Đầu ra và dữ liệu lưu

| Nơi lưu | Khi nào / ý nghĩa |
| --- | --- |
| `meta.model_evaluation` | Mỗi candidate được chấm; giữ cả accepted và rejected |
| Artifact + `dw.dim_model` | Sau khi được chấp nhận; version, feature version, cutoff, SHA-256 và metric |
| `dw.fact_direction_prediction` | Một coin × ngày input × ngày target × model; ghi từ artifact hợp lệ |
| `meta.prediction_batch_lineage` | Nối prediction tới load batch; cần audit đủ mọi batch góp phần tạo feature |

Artifact dùng đường dẫn `DSS_MODEL_PATH`. Khi predict, phải đủ đặc trưng cho cả
ba coin, cùng ngày hôm qua theo UTC; stale/thiếu thì không tạo prediction mới.
Candidate mới bị từ chối không tự xoá model cũ đã chấp nhận.

## 5. API

| Endpoint | Nội dung / trạng thái |
| --- | --- |
| `GET /v1/model/evaluation` | Quyết định, Brier model/baseline và số dòng từng tập. `ready` chỉ nghĩa có bản ghi, không phải model được chấp nhận. |
| `GET /v1/assets/{symbol}/prediction` | Ngày input/target, `probability_up`, model version và Brier. Chưa có prediction → `insufficient_data`; ngày input cũ → `stale`. |
| `GET /v1/assets/{symbol}/prediction/lineage` | Version, checksum và load batches; không có prediction → `unavailable`. |

Các endpoint dùng envelope chung trong [Giao ước dữ liệu](data_contracts_v1.md).
UI/agent chỉ dùng xác suất khi prediction `status=ready` và còn hiệu lực cho ngày
hiện tại; không suy từ evaluation mới nhất rằng prediction chắc chắn có/không.
Ví dụ trong test/demo là giả lập, không được ghi vào dashboard thật.
