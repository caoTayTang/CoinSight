# BTC giờ: lần train và backtest đầu tiên

[Mở báo cáo HTML offline](/reports/hourly-backtest.html).

## 1. DoD và mục tiêu đã chốt trước khi chạy

**DoD kỹ thuật:** dataset đúng thời gian, kiểm chống leakage, train model thật,
validation early stopping, backtest cùng mẫu với baseline, lưu snapshot/model/report,
nạp lại model cho dự báo khớp. Phải báo cả khi model không đạt mục tiêu.

**Một metric, một mục tiêu:**

```text
Relative MAE = MAE log-return model / MAE zero-return
Mục tiêu: Relative MAE ≤ 0,95
```

Zero-return = luôn dự báo log-return bằng 0, tức giá giờ sau bằng giá hiện tại.
Không phải baseline “luôn tăng” của phép thử classification ngày.

0,95 là mục tiêu giảm ít nhất 5% sai số do dự án chọn, không phải cam kết sẽ đạt.
Mean-return 24h và bảng từng tháng vẫn báo để đối chiếu nhưng không tạo thêm cổng
nghiệm thu. Không còn điều kiện thắng 7/12 tháng.

## 2. Dữ liệu được dùng thật

- BTC/USDT Binance Spot, nến `1h`, qua archive downloader → staging → warehouse.
- Nạp bù từ 2020-01: 98 ZIP, 59.537 dòng staging, 0 rejected; load batch 20 thay đổi
  52.865 fact, giữ nguyên 6.672 fact cũ.
- Snapshot từ **2020-01-01 00:00 đến trước 2026-10-18 00:00 UTC**.
- 59.537 nến trên lưới 59.568 giờ: **thiếu 31 giờ**, không tự điền.
- 0 dòng hiện diện vi phạm các kiểm tra OHLC/volume/trade count đã cài.
- Mẫu cắt qua gap hoặc thiếu context bị loại. Không tính return nhảy qua gap.
- 6.672 fact cũ thiếu liên kết archive/checksum; giữ limitation, không gán nguồn suy đoán.

Kiểm độc lập sau khi lưu model:

- 84 ZIP được tham chiếu bởi fact có lineage: hash local khớp manifest.
- 52.865 fact có lineage: OHLC/quote volume/trade count khớp dòng trong ZIP, theo
  độ làm tròn của schema và sai số biểu diễn float.
- Snapshot/model SHA-256 khớp; nạp model và tái tính **56.970 dự báo** khớp tuyệt đối.
- Chi tiết 31 giờ thiếu nằm trong `source_and_replay_checks.json` của run.

Đây là snapshot kho lúc trích xuất; có thể chứa dữ liệu đã chỉnh sửa sau này, chưa
chứng minh lịch sử point-in-time hoặc độ trễ ingestion từng giờ.

## 3. Chia dữ liệu và chống leakage

Chia theo **giờ mở nến mục tiêu**, không random:

| Phần | Khoảng mục tiêu UTC | Mẫu hợp lệ |
| --- | --- | ---: |
| Train | 2020 đến hết 2024 | 41.250 |
| Validation | Năm 2025 | 8.760 |
| Test hồi cứu | 2026-01-01 → 2026-10-17 | 6.960 |

2.597 mẫu train bị loại do warmup/gap/invalid hoặc thiếu target; không loại mẫu
validation/test. Mỗi mẫu có 169 nến đầu vào liên tục; target là nến kế tiếp.

- 78 feature cố định, tất cả chỉ dùng nến đã đóng trước cutoff.
- Không scaler hoặc thống kê học từ toàn bộ validation/test.
- Có test thay đổi giá tương lai: feature quá khứ không đổi.
- Có test context 169 nến, gap, ranh target và thời gian label đóng.
- Một cấu hình XGBoost cố định; không search hyperparameter.
- Early stopping chỉ dùng MAE validation. `best_iteration=57`, tức dùng 58 cây.
- Lưu model và checksum **trước khi** chấm test.
- Không refit hoặc thay feature sau khi nhìn test của lần này.

**2026 đã được xem trong EDA trước đó.** Vì thế đây là test hồi cứu, không gọi là
final test tương lai chưa xem. Sau khi khóa candidate, cần đăng ký kỳ tương lai mới
nếu muốn chứng minh kết quả ngoài mẫu mạnh hơn.

## 4. Kết quả thật — chưa đạt mục tiêu metric

| Phần | Phương pháp | MAE log-return ↓ | Relative MAE ↓ |
| --- | --- | ---: | ---: |
| Validation | Zero-return | 0,003066436 | 1,000000 |
| Validation | Mean-return 24h | 0,003188428 | 1,039783 |
| Validation | XGBoost | 0,003063801 | **0,999141** |
| Test hồi cứu | Zero-return | 0,002944408 | 1,000000 |
| Test hồi cứu | Mean-return 24h | 0,003045518 | 1,034340 |
| Test hồi cứu | XGBoost | 0,002941009 | **0,998846** |

Test: giảm sai số khoảng **0,115%**, chưa tới mục tiêu **5%**.
MAE giá test: baseline 214,38 USDT; model 214,14 USDT.
Directional accuracy test của model: 50,03%, chỉ là metric phụ.

CI bootstrap 95% của Relative MAE test: `[0,99805; 0,99962]`, block 24 giờ liên tục,
500 lần, seed 42. Đây là phép mô tả bất định có giả định, không được dùng để biến
cải thiện rất nhỏ thành tuyên bố lợi thế thực dụng hoặc lợi nhuận.

```text
technical_status: completed
validation_decision: target_not_met
retrospective_test_decision: target_not_met
unseen_future_test_decision: not_evaluated
live_promotion: false
```

Không hạ ngưỡng, không đổi metric, không bật model live để gọi là thành công.

## 5. Artifact và chạy lại

Run đầu:

```text
db02c6e6-4ebb-4235-ba61-cd4b68339c79
```

Thư mục local, được gitignore để không commit dataset/model:

```text
data/models/hourly/db02c6e6-4ebb-4235-ba61-cd4b68339c79/
```

Có `model.ubj`, `snapshot.csv`, `plan.json`, `feature_names.json`, `training_history.json`,
`candidate.json`, `predictions.csv`, `sample_audit.csv`, `monthly_metrics.csv`,
`report.json`, `provenance.json`, `source_and_replay_checks.json`, bản sao code và
Git working-tree diff. Mỗi prediction có cutoff/target/context start, snapshot hash,
đủ batch ID của 169 nến đầu vào và giá dự báo/thực tế để kiểm lại.

```bash
# macOS: XGBoost cần OpenMP (cài một lần)
brew install libomp

# Ghi dữ liệu: tải/nạp BTC giờ từ 2020 qua pipeline batch hiện có
make hourly-backfill

# Train thật từ snapshot DB mới; tạo UUID mới, không ghi đè lần cũ
make hourly-train

# Kiểm độc lập run đã có, không train lại
uv run --python 3.12 --with-requirements scripts/requirements-hourly.txt \
  python -m scripts.check_hourly_run \
  --run-dir data/models/hourly/db02c6e6-4ebb-4235-ba61-cd4b68339c79 \
  --html frontend/public/reports/hourly-backtest.html

# Mở HTML không cần server
open frontend/public/reports/hourly-backtest.html
```

Muốn train lại đúng dữ liệu: dùng `python -m scripts.train_hourly --snapshot PATH`
trong cùng môi trường requirements, code và settings đã lưu. Đây vẫn là lần chạy
mới; không biến test đã xem thành test mới. Tái tính từ model đã lưu chỉ cần lệnh
`check_hourly_run`, không cần fit lại.

Cấu hình: `pipeline/settings.yaml`; code: `pipeline/decision/hourly_features.py`,
`pipeline/decision/hourly_model.py`. Classifier ngày và live feed không bị thay đổi.
API/live inference/promotion không thuộc bước train/backtest này.
