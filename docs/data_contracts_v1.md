# Giao ước dữ liệu và API

Trang này quy định **định dạng tại ranh giới các bước**, không kể lại luồng xử lý.
Xem [Luồng dữ liệu](data_flow.md) để biết cách xử lý; khóa/bảng đầy đủ nằm ở
[Thiết kế kho dữ liệu](dw_design.md).

## 1. Đơn vị và thời gian

`BTCUSDT` là cặp Spot, BTC là tài sản cơ sở và USDT là đơn vị báo giá.
OHLC là giá mở/cao/thấp/đóng; giá và quote volume tính bằng **USDT**.
`volume_base` là số đơn vị coin, `volume_quote` là giá trị giao dịch USDT.
Tất cả mốc thời gian theo UTC; `1m`, `1h`, `1d` là độ dài mỗi nến.
Một số cột tương thích cũ có hậu tố `_usd`; tên đó không đổi đơn vị USDT thực tế.

## 2. Archive → staging

Archive phải đúng cặp, interval, tên file và SHA-256 nguồn.
Archive ngày cần 1 dòng nến ngày hoặc 24 dòng nến giờ.
Mỗi dòng staging giữ:

```text
source_code, symbol, candle_interval, open_time
open_price, high_price, low_price, close_price
volume_base, volume_quote, trade_count
batch_id, source_file
```

`batch_id` ở staging là lần extract; `batch_id` ở fact là lần load.
Hai ID được nối qua `meta.batch_dependency`. Không giả định chúng bằng nhau.
Kết quả quality và chính sách khi nạp lại xem trang thiết kế kho dữ liệu.

## 3. Producer → Kafka

Sự kiện trực tiếp dùng phiên bản schema 1:

| Trường | Quy định |
| --- | --- |
| `schema_version` | Chuỗi `"1"` |
| `symbol`, `pair`, `quote_asset` | Ví dụ `BTC`, `BTCUSDT`, `USDT` |
| `interval`, `mode` | `1m`, `live` |
| `event_time`, `close_time` | Thời điểm mở/đóng của nến nguồn, UTC |
| OHLC | Số hữu hạn, giá dương, tính theo USDT |
| `volume_base`, `volume` | Số coin và quote volume USDT, không âm |
| `source` | `binance-ws` hoặc `binance-rest-backfill` |
| `event_id` | ID ổn định theo cặp/phút; WS và REST của cùng nến dùng chung ID |

Kafka key là cặp giao dịch. Trace context đi trong Kafka headers, không đổi
JSON nghiệp vụ. Replay có `mode=replay`, topic và checkpoint riêng.

## 4. API → giao diện và công cụ trợ lý

Các đường dẫn API `/v1` dùng cấu trúc chung:

```json
{
  "status": "ready",
  "data": {},
  "provenance": {},
  "quality": {},
  "trace_id": "..."
}
```

| Trường | Ý nghĩa |
| --- | --- |
| `status` | Có thể dùng (`ready`), cũ (`stale`), chưa đủ (`insufficient_data`), không khả dụng (`unavailable`) |
| `data` | Kết quả; một số đường dẫn API vẫn giữ số quan sát cũ kèm trạng thái, không được tự coi là mới |
| `provenance` | Nguồn, thời điểm quan sát/tính, theo lô hoặc mô hình nếu có |
| `quality` | Độ mới, số mẫu và cảnh báo |
| `trace_id` | ID phản hồi; không phải mọi ID đều là trace Jaeger |

Mô hình đánh giá `ready` nghĩa là có bản ghi đánh giá, **không có nghĩa mô hình
được chấp nhận**. Điều kiện dùng prediction xem [giao ước ngày](dss_contract_v1.md).
Giao ước giờ có trạng thái/output riêng tại [giao ước giờ](hourly_forecast_contract.md).

## 5. API WebSocket → browser

`WS /v1/assets/{symbol}/stream` gửi:

```text
live.snapshot: type, symbol, sent_at, summary, metric
heartbeat:     type, symbol, sent_at
```

`summary` và `metric` đều là cấu trúc API ở trên. `heartbeat` không chứa giá mới.
Browser kiểm tra symbol và mốc thời gian, không lấy trạng thái kết nối thay cho
freshness/coverage. Nến phút và metric có thể ghi thành công riêng, nên bản chụp dữ liệu không
bảo đảm cả hai đầu ra thuộc cùng micro-batch.

## 6. Phản hồi chat và thông tin chẩn đoán

`POST /v1/agent/chat` trả `answer`, `tools_used`, `model_id` và `trace` tùy chọn.
Trong trace có ID, duration, input/output token, số lần gọi mô hình và `events[]`
(`kind`, `name`, `status`, `duration_ms`). Token là số nhà cung cấp báo trong các lượt
thành công; không phải tổng chi phí thanh toán. Lượt lỗi có thể chưa biết số token.
HTTP error có `X-Trace-ID`; xem cách tìm tại [Theo dõi với Jaeger](observability.md).
Tên trường và đường dẫn API là giao diện kỹ thuật, giữ nguyên dù phần giải thích dùng tiếng Việt.
