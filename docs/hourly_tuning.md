# XGBoost: tuning validation và chẩn đoán có kiểm soát

- [Báo cáo 28 cấu hình](/reports/hourly-tuning.html).
- [Báo cáo Optuna + data/label controls](/reports/hourly-optuna.html).
- [Lần train/backtest đầu](hourly_backtest.md).
- [Độ ổn định theo tháng/quý và đối chứng taker-buy cố định](hourly_signal_diagnostics.md).
- [Phép kiểm tương lai đã khóa và plan BTC + ETH](hourly_future_evaluation.md).
- [Kết quả BTC-only so với BTC + ETH, chạy offline](hourly_cross_asset_results.md).
- [Nghiên cứu tiếp theo với mục tiêu Relative MAE ≤0,97](hourly_mae_097_research.md).

## 1. Giữ nguyên câu hỏi, không đổi metric để tạo thành tích

BTC Binance Spot USDT `1h`, dự báo `ln(C[t+1]/C[t])`. Baseline chính là log-return
bằng 0, tức giá giờ kế bằng giá hiện tại. Metric chính Relative MAE; mục tiêu ≤ 0,95.

Đã thực hiện hai đợt:

1. 28 recipe cố định: depth, loss, pruning, feature ablation, train history, target transform.
2. Optuna TPE 50 trial, seed 42, tuần tự; không GPU, XGBoost CPU hist/2 threads.

Không ghi đè model đầu hoặc bật live. Không chấm lại test 2026.

## 2. Các phần dữ liệu và giới hạn

| Phần | Thời gian mục tiêu UTC | Mẫu |
| --- | --- | ---: |
| Train khả dụng | 2020–2024 | 41.250 |
| Early stopping | Jan–Jun 2025 | 4.344 |
| Selection — objective của search | Jul–Dec 2025 | 4.416 |
| Test 2026 | Không đưa vào dataset tuning | 0 |

Snapshot development chỉ có nến trước 2026-01-01. Một số candidate dùng train gần
hơn, không đổi ranh validation. Mẫu có context 169 nến đã đóng; label là nến kế.

**2025 đã được xem, và search tối ưu chính Jul–Dec.** Vì thế điểm winner có selection
optimism; không phải bằng chứng ngoài mẫu chưa xem. 2026 đã được xem trước đó nên
không dùng lại nó để tuyên bố một final test sạch. Cần kỳ tương lai mới sau khi khóa
candidate nếu muốn kiểm chứng hiệu quả ngoài mẫu.

## 3. Nhìn vào model đầu

- max_depth 3, min_child_weight 20, lambda 10, alpha 0, gamma 0.
- Early stopping giữ 58 cây; trung bình 7,45 lá/cây, max actual depth 3.
- Std dự báo validation ≈ 0,000112; std target ≈ 0,004750.
- Dự báo co gần 0: chưa đủ để kết luận regularization quá mạnh; cũng có thể ít tín hiệu.
- Gamma 0: không phải model đang bị ngưỡng gain pruning mạnh ngay từ đầu.
- Training gain không chứng minh feature có ích ngoài mẫu; có thêm permutation block
  24 giờ trên selection, 3 lần, nhưng đó vẫn chỉ là diagnostic và có feature tương quan.

Đã thử depth lớn hơn; train error giảm nhưng validation không tự động tốt hơn.
Pruning phải đo, không đoán. Không áp sklearn cost-complexity pruning cho XGBoost;
đợt này điều chỉnh gamma, min_child_weight và regularization của XGBoost.

## 4. Feature engineering được thử thật

- Base v1: 78 feature, giữ nguyên code cũ để đối chiếu.
- Expanded v2 experimental: 112 feature.
- Compact v2 experimental: 58 feature, bỏ sparse lag của base, giữ hiện tại/thống kê causal.

Bổ sung:

- Momentum chuẩn hóa volatility; mean/median return theo cửa sổ.
- Khoảng cách tới mean close, high/low quá khứ; vị trí trong range.
- RSI dạng rolling, không phải Wilder EWM lịch sử vô hạn.
- Volatility ratio, return z-score/rank, volume/trade intensity tương đối.
- Signed-candle-volume chỉ là proxy dùng dấu nến, **không** phải actual order flow.

Không học normalization trên toàn validation. Tất cả giới hạn trong 169 nến gốc;
không dùng target, không điền gap. Có test thay đổi tương lai và thay dữ liệu trước
context: feature được phép dùng không đổi. Inference mới cũng chỉ cần 169 nến, không
cần nến label tương lai.

Matched ablation (cùng train 2020–2024, MAE loss, depth 6):

| Feature set | Relative MAE selection |
| --- | ---: |
| Base 78 | 0,998121 |
| Expanded 112 | 0,997469 |
| Compact 58 | 0,997028 |

Thêm feature có ích trong thử nghiệm này, nhưng **không phải thêm càng nhiều càng tốt**.
Không đổi target sang volatility hay horizon khác để làm điểm trông đẹp hơn.

## 5. Kết quả 28 recipe và Optuna

28 recipe hoàn tất khoảng 61 giây (gồm feature và phân tích), winner:

```text
recent_2024_mae
feature=compact/58, max_depth=3, min_child_weight=100
loss=reg:absoluteerror, train=2024, dùng 76 cây
selection Relative MAE=0,995829
selection directional accuracy=53,46%
```

Optuna 50 trial và 11 đối chứng hoàn tất khoảng 28 giây trên lần chạy này (không phải
benchmark chuẩn giữa hai đợt; model/objective/thời gian khởi động khác nhau). Search:

- depth 1–6, learning rate 0,01–0,1.
- min_child_weight 20–300, lambda 0,1–100, alpha 0/0,1/1/10.
- subsample 0,6–1, colsample 0,5–1.
- loss MAE/MSE, feature set, train start, gamma theo objective.
- 1.200 cây tối đa; early stopping 50 vòng trên Jan–Jun 2025.
- Không Optuna-prune trial: dùng early stopping của XGBoost. Gamma là pruning cây,
  không cùng nghĩa với hủy sớm một trial của Optuna.

Target tính bps trong search để đơn vị gamma/alpha rõ; dự báo luôn đổi về log-return
gốc trước tính metric. Model UBJ thô xuất target đã scale nên phải nạp kèm recipe.

Optuna winner, trial 41 (đánh số từ 0):

```text
feature_set=compact, train_start=2024-01-01, 8.784 mẫu train
objective=reg:squarederror, eval_metric=mae
max_depth=3, learning_rate=0,0102235, min_child_weight=129
lambda=5,76046, alpha=10, gamma=10.000 (đơn vị target bps)
subsample=0,658627, colsample_bytree=0,821767
201 cây được dùng sau early stopping
```

| Metric Jul–Dec 2025 | Optuna winner |
| --- | ---: |
| MAE log-return | 0,002741988 |
| Relative MAE | **0,995654** |
| Giảm lỗi so zero-return | **0,435%** |
| Directional accuracy | **52,72%** |
| Reference hướng phổ biến, học trên train | 50,48% |

Mục tiêu giảm 5%: **chưa đạt**. Search cải thiện ít, không tạo đột phá. Không suy ra
hiệu quả test hoặc PnL từ những con số validation đã được dùng chọn candidate.

### MAE 0,004 không phải accuracy 99,6%

MAE là độ lớn sai số trung bình, không là tỷ lệ đúng/sai. 0,004 log-return gần 0,4
điểm phần trăm khi thay đổi nhỏ. Có thể nhìn nhỏ nhưng vẫn lớn so với target giờ.

Directional accuracy tính riêng: `sign(predicted) == sign(actual)`, sign(0)=0.
Reference hướng phổ biến chỉ giúp hiểu metric phụ; không thay baseline zero-return
cho regression. Model tối ưu MAE không nhất thiết có directional accuracy cao nhất.

## 6. Có thật sự cần backfill thêm không?

Không dùng số ảnh/class của object detection để suy ra số mẫu cần cho return giờ.
Các cửa sổ chồng lấn, market regime thay đổi, và tín hiệu dự báo có thể yếu. Không có
mốc 1.500 hay 100.000 mẫu chung bảo đảm thành công.

Đã giữ nguyên recipe của winner đợt 28 và chỉ đổi train start. Cùng validation:

| Train từ | Mẫu train | Relative MAE Jul–Dec |
| --- | ---: | ---: |
| 2020 | 41.250 | 0,998347 |
| 2021 | 33.911 | 0,997275 |
| 2022 | 26.134 | 0,997367 |
| 2023 | 17.374 | 0,996954 |
| 2024 | 8.784 | **0,995805** |
| Jul 2024 | 4.416 | 0,997044 |

Chưa có bằng chứng chỉ thêm năm cũ sẽ giúp. Một năm gần hơn tốt nhất trong đối chứng
này, nhưng rút còn nửa năm cũng kém hơn. Sample size và recency cùng thay đổi nên
không thể quy toàn bộ nguyên nhân cho một yếu tố. Đối chứng chỉ dùng dataset/recipe
này, không khẳng định một năm luôn là tối ưu.

## 7. Negative control để chẩn đoán tín hiệu

Giữ feature/recipe, đảo block 24 giờ của label **train** với 5 seed; validation vẫn
để nguyên. Relative MAE selection:

```text
0,999702; 0,999872; 1,000087; 0,999877; 0,999852
```

Model dùng label thật với cùng recipe khoảng 0,995805, tốt hơn các control đã chạy.
Đây là dấu hiệu hỗ trợ rằng liên kết feature–label có ích trên validation, nhưng
**không phải permutation p-value**: 5 control không lặp lại cả 28+50 trial selection
budget. Không coi đây là bằng chứng thống kê ngoài mẫu hoặc kiếm được tiền.

Chẩn đoán tiếp có ích hơn thêm indicator tùy ý:

- Learning curves/history controls có kiểm soát; kiểm độ ổn định theo thời gian.
- Baseline/label alignment/gap/future mutation checks.
- Feature ablation, train-vs-validation gap, permutation diagnostic.
- Nếu thêm thông tin mới: cần nguồn thật và cutoff rõ, ví dụ taker-buy imbalance
  hoặc dữ liệu cross-asset đã đóng. Không suy ra actual order flow từ OHLC.

Nếu “ADA” là Cardano: cần model/dataset riêng, không bảo đảm dễ hơn BTC. Nếu là
AdaBoost: đó là candidate khác có thể benchmark, không tự động giải quyết tín hiệu yếu.
Đợt này chưa train ADA coin hoặc AdaBoost.

## 8. Chạy lại, kiểm độc lập

```bash
make hourly-tune RUN=data/models/hourly/db02c6e6-4ebb-4235-ba61-cd4b68339c79

make hourly-optuna RUN=data/models/hourly-tuning/5280a844-a30e-4fed-acda-be0430c80c19

open frontend/public/reports/hourly-optuna.html
```

Run IDs:

```text
28 recipes: data/models/hourly-tuning/5280a844-a30e-4fed-acda-be0430c80c19
Optuna:     data/models/hourly-optuna/46037a7b-2793-4bf1-b0f6-306b0a2a102b
```

Từng run có snapshot/hash, plan trước fit, code copy/version, model từng trial,
curves, feature schema, predictions validation, leaderboard và selected recipe/model.
Optuna có `study.sqlite3`; data/models được gitignore, không commit dataset/model.

Kiểm độc lập không train lại:

```bash
uv run --python 3.12 --with-requirements scripts/requirements-hourly.txt \
  python -m scripts.check_hourly_search \
  --run-dir data/models/hourly-optuna/46037a7b-2793-4bf1-b0f6-306b0a2a102b
```

Đã kiểm 28 trial/245.280 predictions và 50 trial/438.000 predictions: nạp model,
tính lại khớp tuyệt đối; không có target 2026. Selected inference dùng 169 nến,
không đọc target, cũng khớp. Tuning chỉ ghi artifact local, không mutate warehouse,
không đổi classifier ngày hoặc bật hourly forecast live.
