# BTC 1h: độ ổn định và đối chứng thông tin taker-buy

## Kết luận

Với dữ liệu, feature và phạm vi mô hình đã thử, chưa tìm được tín hiệu đủ mạnh để
đạt mục tiêu giảm 5% MAE. Không kết luận BTC 1h không có tín hiệu, không loại trừ
mọi bug, và không coi kết quả validation đã chọn là bằng chứng lợi nhuận.

Winner cũ thắng zero-return ở cả 6 tháng selection nhưng lợi ích nhỏ. Một đối chứng
cố định bổ sung taker-buy imbalance **không cải thiện** kết quả tổng. Dừng mở rộng
hyperparameter search trên cùng validation; giữ target next-hour log-return và
ngưỡng Relative MAE ≤ 0,95. Không promote candidate mới.

## 1. Độ ổn định của winner Optuna đã lưu

Tính trực tiếp từ 8.760 dự báo validation của trial 41, không fit để tạo bảng này.
Relative MAE từng nhóm = tổng absolute error model / tổng absolute return;
không lấy trung bình các ratio tháng để tính quý hoặc nửa năm.

| Tháng UTC | N | Relative MAE | Giảm lỗi so zero-return |
| --- | ---: | ---: | ---: |
| 2025-01 | 744 | 0,993507 | 0,649% |
| 2025-02 | 672 | 1,001382 | −0,138% |
| 2025-03 | 744 | 0,996569 | 0,343% |
| 2025-04 | 720 | 1,000845 | −0,085% |
| 2025-05 | 744 | 0,998869 | 0,113% |
| 2025-06 | 720 | 0,998960 | 0,104% |
| 2025-07 | 744 | 0,995500 | 0,450% |
| 2025-08 | 744 | 0,997189 | 0,281% |
| 2025-09 | 720 | 0,998343 | 0,166% |
| 2025-10 | 744 | 0,994153 | 0,585% |
| 2025-11 | 720 | 0,994045 | 0,595% |
| 2025-12 | 744 | 0,996487 | 0,351% |

| Giai đoạn | Relative MAE |
| --- | ---: |
| Q1 | 0,996916 |
| Q2 | 0,999698 |
| Q3 | 0,996926 |
| Q4 | 0,994809 |
| Jan–Jun, dùng cho early stopping trước đây | 0,998121 |
| Jul–Dec, dùng cho selection trước đây | 0,995654 |

Thắng 10/12 tháng mô tả kết quả đã xem, không tạo thêm tiêu chí nghiệm thu hoặc
12 phép thử độc lập. Q2 gần ngang baseline; Q4 tốt hơn Q3 nhưng vẫn cách xa 0,95.
Phân nhóm theo lịch không phải kiểm tra mọi market regime hoặc walk-forward retrain.

Std dự báo của **winner** trên selection ≈ 0,000304; std target ≈ 0,004173.
Các số 0,000112 và 0,004750 trong báo cáo tuning thuộc **model đầu** trên validation,
không phải winner này. Std dự báo nhỏ không trực tiếp đo độ tự tin của mô hình.

## 2. Một đối chứng cố định: thông tin taker-buy thật

[Binance public-data](https://github.com/binance/binance-public-data/#klines) mô tả
kline có taker-buy base và quote volume. Parser kho hiện tại bỏ hai trường này;
thí nghiệm đọc trực tiếp ZIP local, không thay schema hoặc warehouse.

- 72 archive tháng 2020–2025; SHA-256 khớp lineage snapshot khi có, nếu thiếu thì
  kiểm với `.CHECKSUM` chính thức. Lưu nguồn checksum cho từng ZIP trong manifest.
- 52.577 nến snapshot khớp archive về OHLC, quote volume và trade count; quote
  volume cho phép sai số làm tròn 0,005001 USDT vì warehouse lưu 2 chữ số thập phân.
- Taker-buy base/quote đều hữu hạn, không âm và không vượt tổng volume tương ứng.
- Dùng quote volume nguyên bản cùng ZIP cho cả numerator và denominator:
  `imbalance_w = 2 * sum(taker_buy_quote, w) / sum(volume_quote, w) - 1`.
- Bốn cửa sổ khóa trước fit: 1, 6, 24, 168 nến đã đóng. Tổng volume bằng 0 thì
  imbalance trung tính 0; gap vẫn thiếu, không forward-fill hoặc tạo thêm mẫu.
- Tại cutoff chỉ dùng các nến kết thúc trước/đúng cutoff. Đây là aggressive buy
  volume tổng hợp của Binance Spot, không phải order-book imbalance hay toàn thị trường.

Plan ghi trước fit: một cặp compact 58 feature và compact + 4 imbalance. Cùng train
2024, target bps, seed 42, tham số winner, **201 cây cố định**, không early stopping
hoặc chọn lại số cây theo kết quả mới. Hai nhánh chấm trên cùng 8.760 mẫu năm 2025.
Nhánh compact tái tạo dự báo winner trong tolerance rtol 1e-6, atol 1e-10.

| Metric | Compact cũ | Compact + taker |
| --- | ---: | ---: |
| Jan–Jun Relative MAE | 0,998121 | 0,998269 |
| Jul–Dec Relative MAE | **0,995654** | 0,996244 |
| Jul–Dec giảm lỗi | **0,435%** | 0,376% |
| Jul–Dec directional accuracy | 52,72% | 52,26% |
| Q3 Relative MAE | 0,996926 | 0,997490 |
| Q4 Relative MAE | 0,994809 | 0,995416 |

Taker tốt hơn compact ở 3/6 tháng selection (Jul, Sep, Nov), kém hơn ở 3 tháng còn
lại; tổng selection kém hơn. Không có lý do chọn nhánh taker theo phép thử này.
Đây chỉ là một cách biểu diễn và một recipe. Thêm cột cũng thay tập cột mà XGBoost
subsample có thể chọn; không quy mọi chênh lệch thành hiệu ứng thuần của order flow.
Không kết luận taker-buy vô ích với mọi mô hình hoặc horizon.

## 3. Kiểm tra và giới hạn

Đã kiểm hash snapshot/model nguồn, thời gian và label của dự báo, archive checksum,
matching candle, feature bất biến khi cắt bỏ tương lai, context 169 nến, bảo toàn mẫu,
tái tạo nhánh gốc và dự báo model sau reload. Không đọc/chấm target 2026.

2025 vẫn là validation đã xem và đã dùng chọn recipe; phép bổ sung này cũng là
thăm dò hồi cứu. Archive có thể được chỉnh sửa sau này. Cutoff nến đảm bảo tính
causal của phép tính, **chưa chứng minh availability point-in-time hoặc độ trễ live**.
Không có p-value, CI sau selection, PnL hoặc kiểm chứng tương lai mới trong đợt này.

## 4. Artifact và chạy lại

Run hoàn tất:
`data/models/hourly-diagnostics/ab78a7ab-1a06-41c6-afec-d14d6d19afca/`.

Gồm plan trước fit, source manifest, taker snapshot/hash, stability CSV của winner,
CSV đối chứng theo tháng/quý/partition, 2 model UBJ, schema feature, predictions,
checks và bản sao script. Các thư mục lần chạy thất bại trước đó thiếu `checks.json`;
chúng không phải run hoàn tất.

```bash
uv run --python 3.12 --with-requirements scripts/requirements-hourly.txt \
  python -m scripts.diagnose_hourly_signal \
  --run-dir data/models/hourly-optuna/46037a7b-2793-4bf1-b0f6-306b0a2a102b
```

Lệnh tạo UUID mới, chạy đúng một cặp cố định; không ghi đè model nguồn, không search.

## 5. Bước tiếp đã chốt

Không tiếp tục xoay tham số hoặc thử cửa sổ taker khác dựa trên bảng này. Candidate
tham chiếu vẫn là trial 41, không thêm taker và không tự động đưa lên live.

Trước phép kiểm tương lai: khóa model/hash, schema, nguồn đầu vào, độ trễ thực tế,
cutoff và xử lý thiếu dữ liệu; đăng ký khoảng đánh giá bắt đầu sau thời điểm khóa.
Thu dự báo bất biến trước khi label xuất hiện, chờ hết khoảng đã đăng ký rồi chấm
Relative MAE so zero-return trên cùng mẫu. Không dùng lại 2026 đã xem làm final test.
Thu thập dữ liệu tương lai và triển khai lịch chạy chưa được thực hiện trong đợt này.
Đợt tiếp theo đã [khóa kỳ tương lai, cài lịch và đăng ký BTC + ETH](hourly_future_evaluation.md);
chưa có score tương lai tại lúc thiết lập.

Cross-asset/funding/open interest hoặc target khác là thí nghiệm riêng, cần nguồn
và quy tắc thời gian riêng; kết quả taker này không cung cấp bằng chứng cho chúng.
