# Bài toán mô hình: hỏi gì, đầu vào và đầu ra là gì?

Trang này giải thích bằng lời và ví dụ. Định nghĩa kỹ thuật chính thức vẫn ở
[Giao ước dự báo giờ](hourly_forecast_contract.md); không tạo một bộ feature hay
mốc train/test khác mà chưa chốt với nhóm.

## 1. Câu hỏi cần trả lời

> Sau khi một nến BTC/USDT theo giờ đã đóng và được ghi vào kho, lịch sử nến đã biết
> có giúp dự báo log-return của giá đóng **một giờ kế tiếp** tốt hơn hai phương pháp
> đối chiếu đơn giản không?

Đây là **hồi quy (regression)**: dự báo một số, không phải phân loại tăng/giảm và
không xuất xác suất tăng.

Câu hỏi nghiên cứu có thể nhận kết quả **không vượt baseline**. Khi đó không công bố
model như tín hiệu hữu ích; pipeline vẫn phải lưu lần chạy và bằng chứng đánh giá.
Không có mục tiêu đảm bảo lợi nhuận hoặc mua/bán tự động.

## 2. Thời điểm ra quyết định

```text
Nến đầu vào cuối cùng: [10:00, 11:00) UTC
                        ↓ đã đóng, ghi DB
Cutoff:                 11:00 UTC
                        ↓ tạo feature và suy luận
Nến cần dự báo:         [11:00, 12:00) UTC
Giá cần dự báo:          close lúc 12:00 UTC
```

Tại 11:00 có thể biết OHLC/volume của nến 10:00–11:00. Không được đọc high, low,
volume hoặc close của nến 11:00–12:00 vì chúng thuộc tương lai.
Job có thể hoàn tất sau cutoff một chút; giao ước chỉ cho công bố dự báo trực tiếp
khi độ trễ không quá 5 phút và đầu vào hợp lệ. Ngày/giờ ghi trên một dòng warehouse
là **thời điểm mở nến**, không phải thời điểm mọi trường của nến đã được biết.

## 3. Đầu vào thô

Một lần suy luận cho BTC cần **169 nến giờ liên tiếp đã đóng**, từ t−168 đến t:

| Trường | Ý nghĩa | Dùng trực tiếp làm feature? |
| --- | --- | --- |
| `open_time` | Giờ mở UTC; dùng kiểm liên tục, tính giờ/thứ | Không đưa timestamp thô vào model |
| OHLC | Open, high, low, close tính bằng USDT | Biến đổi thành return, range, wick… |
| `volume_quote` | Giá trị giao dịch theo USDT | Log-volume, thay đổi volume, thống kê trượt |
| `trade_count` | Số giao dịch | Log trade count |
| `batch_id`, `loaded_at`, nguồn/checksum | Kiểm tra, truy vết và đóng băng snapshot | **Không** làm feature |

Tại sao 169 thay vì 168? Cần 168 hàng feature, nhưng return của hàng đầu tiên phải
so với giá đóng trước nó. Khi train, cần thêm nến tương lai t+1 để tạo label, tổng
170 nến gốc; khi suy luận không được yêu cầu nến t+1.

Nếu có gap hoặc trường không hợp lệ, loại mẫu và ghi lý do; không tự điền nến giả.
Snapshot kho hôm nay có thể chứa dữ liệu được sửa sau này, nên chưa chứng minh dữ
liệu point-in-time đúng như từng thời điểm lịch sử.

## 4. Đầu vào model — feature khác dữ liệu thô

13 series cơ sở trong giao ước:

- Log-return; return open→close.
- Biên độ high–low; vị trí close trong range.
- Râu nến trên/dưới.
- Log quote volume; thay đổi volume.
- Log số giao dịch.
- Giờ trong ngày: sin/cos; thứ trong tuần: sin/cos.

XGBoost nhận **một hàng feature dạng bảng**: giá trị hiện tại, các độ trễ và thống kê
cửa sổ được liệt kê trong giao ước. Không đưa trực tiếp một file CSV hay “mọi cột trong
DB” vào model. Names/thứ tự feature phải cố định, lưu cùng artifact.

Ví dụ về ý nghĩa (không phải danh sách feature mới):

```text
return hiện tại   → giờ vừa đóng thay đổi bao nhiêu?
return lag 24     → return cách 24 giờ là bao nhiêu?
std return 24 giờ → gần đây biến động mạnh hay yếu?
volume z-score    → volume hiện tại khác mức gần đây thế nào?
```

Feature ở cutoff chỉ được phụ thuộc nến đã đóng không muộn hơn cutoff. Đổi giá tương
lai không được làm thay đổi feature quá khứ; đây phải là test bắt buộc của dataset builder.

## 5. Label khi train và đầu ra khi suy luận

Label thực tế:

```text
y[t] = ln(close[t+1] / close[t])
```

Model đầu tiên: BTC `XGBRegressor`, trả một số hữu hạn:

```text
predicted_log_return
```

Suy ra giá đóng dự báo:

```text
forecast_close_usdt = reference_close_usdt × exp(predicted_log_return)
```

Ví dụ minh họa, **không phải dự báo đã chạy**:

```text
reference_close_usdt = 100.000
predicted_log_return = 0,001
forecast_close_usdt  ≈ 100.100,05 USDT
```

`0,001` là log-return, gần mức tăng 0,1% khi thay đổi nhỏ. Nó **không phải** xác suất
0,1%, 50% hay 100% giá sẽ tăng. Dấu dương cũng không bảo đảm giá tăng.

Kết quả công bố cần kèm coin, cutoff, thời gian mục tiêu, thời gian sinh kết quả,
model version và nguồn snapshot. Đầu ra API chi tiết giữ theo giao ước giờ.

## 6. Thế nào mới gọi là tốt hơn?

So trên **cùng mẫu**, cùng horizon, cùng nguồn:

1. **Zero-return:** dự báo log-return bằng 0 → giá kế tiếp bằng giá vừa đóng.
2. **Mean-return 24h:** dự báo bằng trung bình log-return 24 giờ đã biết.
3. **XGBoost:** dự báo từ feature theo giao ước.

Metric chính: MAE log-return; relative MAE = MAE model / MAE zero-return.
Các metric phụ: RMSE return, MAE giá USDT, directional accuracy.
Không đổi metric chính sau khi nhìn kết quả xấu. Accuracy của phép thử ngày trong
EDA là bài học riêng, không thay điều kiện chấp nhận hồi quy giờ.

Theo yêu cầu mới, chốt **một metric, một mục tiêu: Relative MAE ≤ 0,95** so với
zero-return, tức giảm ít nhất 5% sai số. Mean24 và điểm tháng chỉ để đối chiếu/chẩn đoán;
không còn điều kiện thắng 7/12 tháng. Mục tiêu này đặt trước lần train đầu, không phải
cam kết khả thi. Kết quả test 2026 là hồi cứu; thành công trên test tương lai chưa xem
vẫn cần kỳ mới. Vượt metric cũng không chứng minh sinh lời.

## 7. Train/validation/test: việc gì đã chốt, việc gì chưa làm?

Giao ước hiện có:

| Khoảng target | Vai trò thiết kế ban đầu |
| --- | --- |
| 2020 đến trước 2025 | Train |
| Năm 2025 | Validation: chọn candidate/early stopping |
| Năm 2026 | Test hồi cứu theo thiết kế ban đầu |

**Cảnh báo:** năm 2026 đã xuất hiện trong EDA ngày và kết quả backtest được xem. Không
còn được khẳng định đây là test hoàn toàn chưa xem để tiếp tục chọn feature/model.
Điều này không làm dữ liệu vô dụng, nhưng thay đổi độ mạnh của kết luận đánh giá.

Quy trình tiếp theo:

1. Ghi lại mọi giai đoạn đã xem; coi kết quả 2026 là khám phá/hồi cứu.
2. Giữ target, horizon, danh sách feature, baseline và metric theo giao ước; không
   chỉnh theo điểm 2026.
3. Nạp đủ train/validation giờ, tạo snapshot và dataset builder có test chống leakage.
4. Chỉ chọn candidate bằng train/validation và ghi lại tất cả lần thử.
5. Sau khi khóa feature/config/artifact, xác định một khoảng **tương lai chưa xem**
   với đủ số mẫu và giao thức chấm điểm; công bố mốc trước khi thu thập/chấm điểm.
6. Nếu thay thiết kế sau khi xem test mới, coi test đó đã dùng và cần kỳ mới khác.

Chưa tự đổi mốc contract hoặc giả định rằng đã có đủ test tương lai. “Chốt feature”
trong tài liệu khác với khóa kỹ thuật: còn cần code builder, danh sách/thứ tự feature,
config, snapshot và checksum artifact mới có thể tái hiện một candidate cụ thể.

## 8. Trạng thái thực tế sau EDA

Đã làm:

- EDA ngày từ DB local, kiểm đủ nến, snapshot và các ví dụ tính tay.
- Kiểm checksum local của archive có lineage; đối chiếu dữ liệu với ZIP.
- Kiểm một quy tắc dự báo ngày cố định và baseline; không tune theo kết quả.
- Ghi rõ phần giữ riêng đã xem không phải test cuối còn nguyên vẹn.

**Đã bổ sung theo yêu cầu train thật:** backfill BTC giờ từ 2020, feature builder
causal có test, một XGBoost candidate với validation early stopping, backtest 2026,
model UBJ nạp lại được và artifact đầy đủ. Xem [báo cáo lần chạy](hourly_backtest.md).

**Chưa làm:** promote model, API dự báo giờ hoặc kiểm test tương lai. Model đầu chưa
đạt Relative MAE ≤ 0,95. Không dùng kết quả test để chỉnh lại candidate của cùng lần chạy.

## 9. Đọc cùng bằng chứng thật

- [Bản kiểm chứng bằng số thật](/reports/eda-checks.html).
- [Báo cáo EDA](/reports/eda.html).
- [Cách chạy lại EDA](eda_report.md).
- [Định nghĩa kỹ thuật dự báo giờ](hourly_forecast_contract.md).
