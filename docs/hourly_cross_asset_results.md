# BTC-only so với BTC + ETH: kết quả chạy offline

Đã chạy đúng một thí nghiệm cố định, trong một phiên trên laptop; không chờ 30 ngày
và không cài lịch nền. Thêm 7 feature ETH **gần như không làm giảm MAE** trong phép
thử này. Relative MAE gộp từ **0,998232 → 0,998184**, vẫn không đạt mục tiêu **0,95**.

## Thiết kế khóa trước khi tải dữ liệu và fit

Plan mới dùng `execution_mode=offline_retrospective`, không phụ thuộc kỳ tương lai.
Plan cũ có gate tương lai được giữ nguyên làm artifact của thiết lập đã hủy; không
sửa plan cũ để giả như nó đã hoàn tất.

- Target BTC Binance Spot 1h: `ln(C[t+1]/C[t])`; baseline zero-return.
- Hai nhánh: compact BTC 58 feature, so với cùng bộ đó cộng 7 feature ETH.
- Giữ recipe trial 41, seed 42, 201 cây cố định, CPU/2 threads; không search hoặc
  early stopping. Target fit nhân 10.000, prediction đổi về log-return trước chấm.
- Bốn fold quý 2025; mỗi fold train một lần trên 12 tháng ngay trước quý đó.
- Cùng train/validation timestamp và label BTC giữa hai nhánh. Không random split.
- ETH gồm return 1h, momentum 6/24/168h, std return 24h, BTC–ETH return spread 1h,
  correlation return 168h; chỉ dùng nến đã đóng và context 169 nến liên tục.
- Snapshot BTC có sẵn được kiểm hash; 25 ZIP ETH Dec 2023–Dec 2025 được kiểm SHA-256
  với checksum nguồn. Không đọc/chấm target 2026.

## Kết quả trên cùng timestamp

| Validation UTC | Mẫu train mỗi nhánh | Mẫu validation mỗi nhánh | BTC-only Relative MAE | BTC + ETH Relative MAE |
| --- | ---: | ---: | ---: | ---: |
| Q1 2025 | 8.784 | 2.160 | 0,996916 | 0,996912 |
| Q2 2025 | 8.760 | 2.184 | **0,999679** | 1,001207 |
| Q3 2025 | 8.760 | 2.208 | 1,000400 | **0,999243** |
| Q4 2025 | 8.760 | 2.208 | 0,997031 | **0,996298** |
| **Gộp cả năm** | — | **8.760** | **0,998232** | **0,998184** |

Coverage ghép cặp **100%** ở cả bốn quý; không bỏ giờ validation vì thiếu ETH.
Ratio gộp tính từ tổng absolute error, không lấy trung bình ratio từng quý.

| Metric cả năm 2025 | BTC-only | BTC + ETH |
| --- | ---: | ---: |
| MAE log-return | 0,003061014 | 0,003060868 |
| Zero-return MAE, cùng mẫu | 0,003066436 | 0,003066436 |
| Giảm lỗi so zero-return | 0,1768% | 0,1816% |

ETH giảm MAE thêm khoảng **0,00475% so với BTC-only**, không phải giảm thêm 0,475%
hay đạt mục tiêu giảm 5%. ETH tốt hơn ở 3/4 quý, nhưng Q1 gần như hòa và Q2 kém hơn;
không có cải thiện lớn hoặc đồng đều để khẳng định ETH giải quyết được bài toán.

Không so trực tiếp ratio cả năm này với **0,995654** của winner cũ trên Jul–Dec:
khác khoảng chấm và ở đây có refit theo quý trên rolling train history.

## Giới hạn và quyết định

2025 và recipe tham chiếu đã được dùng cho selection trước đây. Chronological
replay này kiểm tra pipeline và mức ổn định theo thời gian; **không phải unseen
test**, không có kết luận thống kê hoặc PnL. Thêm cột cũng thay không gian lấy mẫu
cột của XGBoost, nên chênh lệch là của hai pipeline cùng recipe, không phải tác
động thuần của ETH. Archive không chứng minh availability point-in-time.

Kết luận giới hạn ở đúng 7 feature và recipe đã thử: **chưa có cải thiện đáng kể
về mặt thực dụng; mục tiêu 0,95 chưa đạt**. Không promote nhánh ETH, không tự chạy
thêm recipe hoặc mở lại scheduler. Kết quả này không loại trừ mọi cách dùng ETH,
funding hoặc open interest.

## Artifact và kiểm tra

Run hoàn tất:
`data/models/hourly-cross-asset/0255e6cb-7c66-4615-acfc-e0c6a654c19c/`.

Plan SHA-256:
`2e1994a16f2d3e6c71b2dc25f192777002e91065c0e9f4f35e5a57b75d2dfb53`.

Gồm plan, code đóng băng, snapshot BTC, 25 ZIP/checksum ETH, source manifest,
8 model/schema/prediction, report gộp và `offline_checks.json`.

Đã kiểm:

- Hash 25 archive và 8 model; causal prefix và context 169 nến.
- Model reload cho prediction khớp tuyệt đối ở từng fold.
- Tính lại metric từ 17.520 prediction đã lưu; 8.760 giờ duy nhất mỗi nhánh.
- Label khớp log-ratio actual/reference close và đúng ranh từng quý.
- Hai nhánh có cùng timestamp và metadata/label trên mọi fold.
- 38 test feature, temporal ordering, gate/offline mode và thu dự báo trước đó qua.

Đọc lại run có sẵn, không fit lại:

```bash
data/models/hourly-runtime/venv/bin/python -m scripts.hourly_cross_asset run \
  --experiment data/models/hourly-cross-asset/0255e6cb-7c66-4615-acfc-e0c6a654c19c
```

Chạy lại từ một UUID mới, không tạo lịch nền:

```bash
data/models/hourly-runtime/venv/bin/python -m scripts.hourly_cross_asset init --offline \
  --source data/models/hourly-optuna/46037a7b-2793-4bf1-b0f6-306b0a2a102b

# Dùng đường dẫn UUID mà lệnh init in ra:
data/models/hourly-runtime/venv/bin/python -m scripts.hourly_cross_asset run \
  --experiment data/models/hourly-cross-asset/<uuid-moi>
```
