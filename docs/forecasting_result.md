# Dự báo BTC theo giờ: kết quả

**Kết luận: lợi suất BTC giờ tới gần như không dự báo được từ dữ liệu thị trường công khai. Model tốt nhất chỉ
hơn baseline "dự báo lợi suất 0" chưa tới 1% MAE, nên được dùng như một tool của agent kèm cảnh báo đó, không phải
tín hiệu giao dịch.**

## Câu hỏi

Dự báo log return của giờ BTC/USDT kế tiếp từ thông tin có tại thời điểm cắt. Metric là **Relative MAE** =
MAE của model / MAE khi luôn dự báo 0. Dưới 1,0 là hơn baseline. Định nghĩa đầy đủ ở [Giao ước](hourly_forecast_contract.md).

## Vì sao con số đáng tin

- **Feature chỉ dùng quá khứ.** Feature tại giờ *t* chỉ dùng nến đã đóng trước hoặc tại *t*; sửa dữ liệu tương lai
  không đổi feature cũ, và có test kiểm tra (`tests/decision/test_hourly_features.py`).
- **Chia thời gian có khoảng đệm.** Train, validation và test không chồng nhau, kể cả horizon của target.
- **Kế hoạch khóa trước khi train.** Cách chia, metric và danh sách ứng viên được ghi trước, nên model không được
  chọn bằng cách thử trên test.
- **Có khoảng bất định.** Circular block bootstrap, khối 168 giờ, 2.000 lần lấy mẫu.

## Kết quả

| Model | Giai đoạn | Số giờ | Relative MAE |
|---|---|---:|---:|
| Ensemble tốt nhất (2× CatBoost, trọng số cố định) | 7–12/2025 (tập chọn, đã xem nhiều lần) | 4.416 | **0,9929** (bootstrap 95%: 0,9900–0,9961) |
| CatBoost ứng viên | như trên | 4.416 | 0,9940 |
| XGBoost tốt nhất | như trên | 4.416 | 0,9957 |
| TCN / LSTM, chỉ BTC hoặc gộp 8 asset | như trên | 4.416 | 0,9974–0,9987 |
| Bundle đóng băng đang phục vụ agent | 1–10/2026, nhìn lại | 6.984 | **0,9970** |

Mục tiêu 0,97 được đặt từ đầu và giữ nguyên. **Không đạt.** Đã thử các họ model khác, feature trong giờ, phái sinh,
order book, liên asset và ensemble; script lưu ở `research/hourly/`, nhật ký đầy đủ ở
[hourly_mae_097_research.md](hourly_mae_097_research.md).

Đánh giá đóng băng năm 2026 còn có: độ chính xác hướng **52,96%**, balanced accuracy **52,98%**, RMSE **0,00455452**
so với **0,00454400** của baseline lợi suất 0. MAE thấp hơn không làm mọi metric tốt hơn. So sánh chi tiết các thí
nghiệm (28 công thức ban đầu, 50 lượt Optuna và các so sánh sau) ở [báo cáo HTML](/reports/hourly-research-summary.html).

## Ý nghĩa cho sản phẩm

- Dự báo là một tool của agent; mô tả tool ghi rõ Relative MAE 0,997. Agent không được trình bày nó như tín hiệu
  giao dịch (eval có case `trading_advice` kiểm tra).
- Phần kỹ thuật đáng giá là quy trình: feature không rò rỉ, kế hoạch khóa trước, có khoảng bất định. Kết quả là một
  kết luận âm có cơ sở, không phải một con số "95% chính xác" do overfit.

## Phát hiện bất thường

Isolation Forest train trên 2023–2024, hiệu chỉnh trên 2025, đánh dấu 78 trên 6.984 giờ năm 2026 (1,12%), so với
101 giờ (1,45%) của quy tắc median/MAD cố định. Không có nhãn bất thường, nên đây là tỉ lệ cảnh báo, không phải
precision hay recall.

## Phục vụ và theo dõi

Bản export để phục vụ được so với cả 6.984 dự báo đã lưu (chênh lệch log return lớn nhất khoảng 1,71e-15). Điều
này chứng minh phục vụ đúng như lúc nghiên cứu, không chứng minh độ chính xác trong tương lai.

Dự báo mới được ghi và chấm trong prediction ledger; drift đầu vào và kết quả đã chấm là hai bằng chứng riêng.
Xem [Gắn một mô hình mới](model_integration.md).
