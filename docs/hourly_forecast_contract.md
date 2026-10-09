# Giao ước dự báo giá theo giờ

Trạng thái: **chốt làm cơ sở triển khai trên nhánh `feature/hourly-forecast-contract`**,
09/10/2026. Đây là quyết định triển khai theo yêu cầu của chủ dự án, chưa phải
xác nhận duyệt của Dương. API và mô hình mô tả dưới đây **chưa được triển khai**.
Đề xuất gốc: [forecasting_design.md](forecasting_design.md).
Mô hình phân loại ngày và [giao ước hiện tại](dss_contract_v1.md) tiếp tục độc lập.

## 1. Bài toán và mô hình đầu tiên

Sau khi một nến Spot Binance `1h` đóng, dự báo log-return của nến kế tiếp:

```text
y[t] = ln(close[t+1] / close[t])
forecast_close_usdt = close[t] × exp(predicted_log_return)
```

- Coin được hỗ trợ trong giao ước: BTC, ETH, SOL; triển khai và huấn luyện **BTC trước**.
- Một mô hình riêng cho mỗi coin. Kỳ dự báo cố định một giờ, đơn vị báo giá USDT.
- Mô hình đầu tiên: **XGBoost `XGBRegressor`**, CPU, không huấn luyện sẵn.
- Hai phương pháp đối chiếu bắt buộc: return bằng 0 và return trung bình 24 giờ gần nhất.
- Không biến return dự báo thành `probability_up`; hồi quy không xuất xác suất.
- Không có mua/bán tự động, khoảng tin cậy hoặc đảm bảo lợi nhuận trong giao ước này.

XGBoost được chọn để thử toàn bộ tập dữ liệu → đánh giá → tệp mô hình trước khi thêm
học sâu. GRU/LSTM/PatchTST/iTransformer giữ để nghiên cứu tiếp theo.

## 2. Các mốc thời gian — tất cả UTC

Dùng khoảng thời gian nửa mở `[open_time, close_boundary)`; không dùng giây cuối
`xx:59:59` làm ranh giới vì độ chính xác mốc thời gian của nguồn có thể khác nhau.

| Trường | Định nghĩa | Ví dụ |
| --- | --- | --- |
| `input_open_time` | Giờ mở của nến cuối cùng dùng làm đầu vào, tức `t` | 10:00 |
| `cutoff_time` | `input_open_time + 1h`; đầu vào chỉ gồm nến đóng không muộn hơn mốc này | 11:00 |
| `generated_at` | Thời điểm suy luận thực sự hoàn tất | 11:02 |
| `target_open_time` | `cutoff_time`; giờ mở nến cần dự báo | 11:00 |
| `target_close_time` | `cutoff_time + 1h` | 12:00 |

Ví dụ trên dùng nến `[10:00,11:00)` để dự báo giá đóng của `[11:00,12:00)`.
`cutoff_time` **không phải** mốc thời gian của lần chạy job và **không phải** giờ mở đầu vào.

Suy luận trực tiếp chỉ được công bố nếu `0 <= generated_at - cutoff_time <= 5 phút`,
nến đầu vào đã ghi thành công và mọi đặc trưng hợp lệ. Quá 5 phút trả `stale`, không tạo
dự báo mới mang danh hiện tại. Dự báo đã công bố hết hiệu lực khi
`now >= target_close_time`; lịch sử vẫn được giữ để chấm điểm.
Mốc 5 phút là SLA ban đầu của dự án, không phải tính chất của Binance.

## 3. Kho dữ liệu → tập dữ liệu

Nguồn huấn luyện: `dw.fact_ohlcv_hourly`, join `dw.dim_asset` và `dw.dim_source`, chỉ
`source_code='binance'`. Khóa tự nhiên: `(source, symbol, open_time)`.

Các cột cần có: `open_time`, OHLC, `volume_quote`, `trade_count`, `batch_id`,
`loaded_at`. Giá và quote volume tính theo USDT; không gọi là USD.

Điều kiện nhận dữ liệu:

- Giờ mở nằm đúng ranh giờ UTC, khóa không trùng; trùng lặp làm bản chụp dữ liệu fail.
- OHLC hữu hạn, dương; high/low bao được open và close.
- Quote volume hữu hạn, không âm; trade count nguyên, không âm, không null.
- Chỉ nến đã đóng tại thời điểm extract bản chụp dữ liệu.
- Sort theo coin/thời gian, reindex theo lưới giờ. Không forward-fill, interpolate
  Hoặc impute nến thiếu. Mẫu cắt qua gap/row không hợp lệ bị loại và đếm lý do.

### Cửa sổ quan sát và dữ liệu bổ sung

Chuỗi có **168 đặc trưng rows** tại `t-167 … t`. Để tính return/volume-change
của row đầu tiên, phải có thêm nến `t-168`: tổng **169 nến gốc liên tiếp**.
Nhãn cần nến `t+1`, nên mẫu huấn luyện cần 170 nến liên tiếp `t-168 … t+1`.
Suy luận cần 169 nến; không được yêu cầu hay đọc mục tiêu chưa tồn tại.

Giới hạn chung cho mọi mô hình: không dùng gốc đầu vào trước `t-168`.
XGBoost dùng độ trễ `0,1,2,3,6,12,24,48,72,167`; **bỏ độ trễ 168 của return** vì
nó cần thêm nến `t-169`, vượt giới hạn. Momentum 168 vẫn hợp lệ: `ln(C[t]/C[t-168])`.

13 đặc trưng gốc theo đề xuất: log-return, open-close return, high-low range,
close position, upper/lower wick, log quote volume, volume change, log trade count,
hour sin/cos và weekday sin/cos (Monday=0). `close_position=0.5` khi high=low;
không chia cho epsilon tùy ý. Wick dùng `max(O,C)` / `min(O,C)` đúng công thức đề xuất.

XGBoost lấy cả 13 đặc trưng tại `t`, cộng độ trễ khác 0 của sáu series trong đề xuất;
momentum `6/12/24/72/168`, std return `6/24/72/168` (`ddof=0`),
quote-volume z-score `24/168` (bằng 0 khi std=0). Cửa sổ cửa sổ trượt gồm row hiện tại.
Đặc trưng names/thứ tự được lưu cùng tệp mô hình; chỉ cột đã liệt kê được đưa vào mô hình.
Không dùng gốc mốc thời gian, mục tiêu, giá tương lai, theo lô ID hoặc thời điểm nạp làm đặc trưng.

## 4. Tập dữ liệu → huấn luyện và đánh giá

Phân chia theo **`target_open_time`**; không random phân chia:

| Partition | mục tiêu open time |
| --- | --- |
| huấn luyện | Từ lịch sử khả dụng năm 2020 đến trước 2025-01-01 |
| tập kiểm định | Từ 2025-01-01 đến trước 2026-01-01 |
| Tập kiểm tra cuối | Từ 2026-01-01 đến ngày kết thúc bản chụp dữ liệu đã đóng băng |

Context được phép đi qua ranh partition về quá khứ. Mọi nhãn huấn luyện phải đóng
không muộn hơn mốc chặn dữ liệu của mẫu tập kiểm định đầu tiên; kiểm tra tương tự khi
đánh giá walk-forward. Không học tham số tiền xử lý trên validation/test.
Tập dữ liệu thiếu partition phải fail rõ ràng, không tự đổi phân chia.

Lần đầu dùng một cấu hình cố định, không siêu tham số search:

```text
objective=reg:squarederror, eval_metric=mae, tree_method=hist
n_estimators=500, learning_rate=0.03, max_depth=3
min_child_weight=20, subsample=0.8, colsample_bytree=0.8
reg_alpha=0, reg_lambda=10, random_state=42, n_jobs=2
early_stopping_rounds=30, eval_set=validation only
```

XGBoost không cần bộ chuẩn hóa ở lần đầu. dừng sớm dùng tập kiểm định MAE, tuyệt đối
không dùng tập kiểm tra cuối. Lưu best iteration và dùng đúng iteration đó khi suy luận.
Các tham số thuộc `settings.yaml` khi triển khai; đường dẫn/DB thuộc `.env`.

Metric trên cùng mẫu cho cả ba phương pháp:

- Chính: MAE log-return; Relative MAE = mô hình MAE / zero-return MAE.
- Phụ: RMSE return, MAE giá USDT, directional accuracy với `sign(0)=0`.
- Báo cáo toàn tập kiểm định và từng tháng, kèm số mẫu và tỷ lệ bị loại.
- Phương pháp đối chiếu MAE bằng 0: Relative MAE là null, không chia 0; mô hình ứng viên không đạt điều kiện chấp nhận.

Điều kiện chấp nhận nghiên cứu ban đầu: MAE toàn tập kiểm định thấp hơn **cả hai** phương pháp đối chiếu và
thắng zero-return ở ít nhất 7/12 tháng tập kiểm định; mỗi tháng phải có tối thiểu
500 mẫu hợp lệ. Thiếu độ phủ → `insufficient_data`; không thắng → `rejected`.
Đây là tiêu chí do dự án chọn, không phải bằng chứng về lợi nhuận giao dịch.

Sau khi khóa đặc trưng, cấu hình và mô hình ứng viên, chạy tập kiểm tra cuối để báo cáo; điểm tập kiểm tra
không được dùng để chọn mô hình hoặc huấn luyện lại. Nếu sửa thiết kế sau khi xem tập kiểm tra, đánh dấu
tập kiểm tra đã bị sử dụng và dành kỳ tương lai mới làm tập giữ riêng. Chưa tự động đưa vào sử dụng trực tiếp
chỉ vì vượt điều kiện chấp nhận tập kiểm định: còn phải kiểm chứng độ mới, phục hồi lỗi và tệp mô hình.

## 5. Lần chạy, tệp mô hình và nguồn dữ liệu

Mỗi lần huấn luyện có UUID `run_id` mới, không ghi đè tệp mô hình lần chạy cũ. Lưu cả lần chạy bị
từ chối. `model_version=run_id`; schema đặc trưng có tên cố định `hourly-return-v1`.

Mỗi thư mục kết quả phải có:

- `model.ubj`, SHA-256; định dạng gốc XGBoost, không chỉ pickle.
- Bản chụp dữ liệu và SHA-256, phiên bản truy vấn/mã nguồn, mã commit Git và trạng thái thay đổi chưa commit.
- Tên và thứ tự đặc trưng, cấu hình, hạt giống ngẫu nhiên, phiên bản thư viện và vòng huấn luyện được chọn.
- Ranh các tập, ngày kết thúc bản chụp, số mẫu và số mẫu bị loại theo lý do/split.
- Metric của mô hình và hai phương pháp đối chiếu, quyết định chấp nhận và thời gian huấn luyện.
- Toàn bộ ID các batch nguồn của bản chụp dữ liệu; mỗi dự báo truy được đủ batch của
  169 nến đầu vào, không chỉ batch của nến cuối cùng.

Bản chụp dữ liệu là **lịch sử kho dữ liệu tại lúc trích xuất**, có thể chứa chỉnh sửa sau này;
chưa chứng minh đây là dữ liệu được biết tại từng thời điểm quá khứ. Ghi rõ hạn chế
dữ liệu đúng thời điểm lịch sử này trong báo cáo đánh giá hồi cứu. Giữ bản chụp dữ liệu để không huấn luyện lại trên
dữ liệu đã thay đổi mà vẫn gọi là cùng tập dữ liệu.

## 6. Dự báo → API/giao diện/trợ lý

Đường dẫn API riêng: `GET /v1/assets/{symbol}/hourly-forecast`. Giữ envelope hiện có:
`{status, data, provenance, quality, trace_id}`. Không đổi đường dẫn API ngày `/prediction`.

`data` khi sẵn sàng gồm:

```text
symbol, pair, quote_currency="USDT", horizon_hours=1
input_open_time, cutoff_time, generated_at, target_open_time, target_close_time
reference_close_usdt, predicted_log_return, forecast_close_usdt
model_name="xgboost", model_version, feature_version="hourly-return-v1"
```

Mọi mốc thời gian là RFC3339 UTC; số phải hữu hạn, giá tham chiếu và giá dự báo > 0.
`provenance` mang ID/checksum bản chụp và liên kết nguồn tới mô hình, lần chạy, đầu vào.
Giá thực tế chỉ được ghi sau khi nến mục tiêu đóng; không nằm trong phản hồi dự báo hiện tại.

| Trạng thái | Nghĩa / hành vi |
| --- | --- |
| `ready` | mô hình đã đưa vào sử dụng, đầu vào đủ/mới và dự báo chưa hết hạn |
| `stale` | đầu vào quá SLA hoặc dự báo hết hạn; `data=null` |
| `insufficient_data` | Thiếu nến, đặc trưng hoặc mô hình chưa vượt điều kiện chấp nhận; `data=null` |
| `unavailable` | Chưa có mô hình được đưa vào sử dụng hoặc lỗi dịch vụ phụ thuộc; `data=null` |

`quality.warnings` chứa mã lý do phân biệt `input_gap`, `input_stale`,
`forecast_expired`, `model_rejected`, `no_promoted_model`, `dependency_error`.
Coin ngoài BTC/ETH/SOL trả HTTP 422. BTC được triển khai trước; coin chưa có
mô hình trả `unavailable`, không trả dự báo của BTC thay thế.
Giao diện ghi “Dự báo giá đóng lúc … UTC”, tách khỏi giá thực tế; trợ lý chỉ đọc đầu ra.

## 7. Vận hành và phạm vi bước đầu

```text
ZIP lịch sử → kho nến giờ → tập dữ liệu cố định → đối chiếu + BTC XGBoost
                                               → đánh giá + tệp mô hình

Nạp nến giờ mới [CHƯA CÓ] → kiểm đầu vào → mô hình đã đưa vào sử dụng
                                          → API dự báo giờ [CHƯA CÓ]
```

ZIP đóng gói theo ngày/tháng phục vụ lịch sử huấn luyện. suy luận sau này lấy nến `1h` đã đóng
qua Binance REST, qua cùng bước kiểm tra dữ liệu rồi upsert kho dữ liệu; dùng ZIP để đối soát.
Cần lưu nguồn kênh truyền và phiên bản dữ liệu và kiểm chứng đặc trưng khi huấn luyện và suy luận giống nhau trước khi bật.
Không dùng tổng hợp Spark 7 ngày hay đủ 60 phút nhưng chưa kiểm tính liên tục để
giả làm nến giờ. Airflow huấn luyện có thể chạy hằng tuần; suy luận phải được kích hoạt
sau đầu vào hợp lệ, không chỉ đặt lịch rồi giả định dữ liệu đã nạp xong.

Hiện kiểm tra DB ngày 09/10/2026: BTC/ETH/SOL mỗi coin 6.672 nến giờ,
01/01/2026–05/10/2026. **Thiếu train/validation 2020–2025**. Bước tiếp theo là
nạp bù BTC, đóng băng bản chụp và viết tập dữ liệu/kiểm thử rồi huấn luyện cấu hình trên.
Không dùng tập kiểm tra 2026 làm huấn luyện để bỏ qua thiếu dữ liệu.

Nghiệm thu bước đầu: kiểm thử khoảng thiếu, ranh tập và thay đổi dữ liệu tương lai đều đạt;
huấn luyện thật BTC xuất tệp mô hình và báo cáo phương pháp đối chiếu, kể cả bị từ chối; tập kiểm tra cuối chưa
bị dùng để tinh chỉnh. Schema đăng ký mô hình, API, nạp giờ mới và giao diện dự báo là bước tiếp sau.

Tham chiếu API thư viện: [XGBoost Python API](https://xgboost.readthedocs.io/en/stable/python/python_api.html).
