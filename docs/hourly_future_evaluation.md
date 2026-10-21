# BTC 1h: phép kiểm tương lai và thí nghiệm BTC + ETH đã đăng ký

> **ĐÃ HỦY LỊCH THEO YÊU CẦU NGƯỜI DÙNG.** Kỳ 30 ngày trên laptop không được
> chấp nhận. Cả hai LaunchAgent đã được unload, xóa plist và kiểm tra không còn
> được đăng ký. Không còn job thu dự báo hoặc tự chạy BTC + ETH. Code và artifact
> giữ lại để tham khảo; phần dưới mô tả thiết lập ban đầu, không phải lịch đang chạy.

Thí nghiệm BTC + ETH sau đó được phép chạy offline ngay bằng một plan mới, không
đợi kỳ tương lai. Xem [kết quả offline đã hoàn tất](hourly_cross_asset_results.md).

## Trạng thái và quyết định

Đã khóa candidate trial 41, code, schema, tham số và phiên bản runtime; đã cài lịch
thu dự báo local. Kỳ kiểm tương lai bắt đầu **2026-10-18 18:00 UTC**, kết thúc
**2026-11-17 18:00 UTC**: giờ Việt Nam **19/10 01:00 → 18/11 01:00**. Đây là 30 ngày,
720 target giờ. Tại lúc cài lịch, chưa đến target đầu: **0 dự báo study, 0 label**.
Preflight với REST thật đã lấy đủ 169 nến và chạy inference thành công; preflight
không được tính vào study.

BTC + ETH được đăng ký và xếp lịch riêng, **chưa tải ETH hoặc fit trên dữ liệu thị
trường**. Runner chỉ được chạy sau khi study tương lai có kết quả cuối hợp lệ.
Không điều chỉnh recipe cross-asset theo kết quả tương lai.

**0,95 được giữ làm mục tiêu, chưa có bằng chứng cho thấy khả thi.** Các thử nghiệm
cũ không đủ để kết luận ngưỡng đó bất khả thi với mọi dữ liệu công khai. Không hạ
ngưỡng để gọi thành công. Nếu hết kỳ và đủ coverage mà Relative MAE >0,95 thì báo
`target_not_met`; đây là đánh giá candidate đã khóa trong kỳ này, không phải chứng
minh giới hạn của toàn bộ bài toán. Đổi target/horizon là dự án khác.

## 1. Protocol tương lai

Candidate nguồn:
`data/models/hourly-optuna/46037a7b-2793-4bf1-b0f6-306b0a2a102b/`.

- Model trial 41, compact 58 feature, 201 cây; không refit, recalibrate hoặc thêm feature.
- Model SHA-256: `6c5bb7020949b3f1182ca0ca92185e8f8e3ff638b3a3016c83d4e79e937b074d`.
- Target giữ nguyên `ln(C[t+1]/C[t])`; reference close được đóng băng cùng dự báo.
- Baseline luôn return 0, chấm trên đúng cùng các label có dự báo hợp lệ.
- Nguồn inference/label: Binance Spot BTCUSDT `1h` REST, qua public market-data host.
  [Tài liệu Binance](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market)
  mô tả timestamp, close time và schema kline.
- Scheduler chạy ở phút 01 mỗi giờ. Request chỉ lấy 169 nến kết thúc trước target
  open; không request nến target hoặc dùng giá target đang chạy để dự báo.
- Phải ghi dự báo trong 120 giây sau target open, trước label close. Ghi rõ giờ issue
  từ exchange, giờ local, input cutoff và độ trễ. Đây là dự báo phát hành trễ tối đa
  2 phút so với đầu giờ, **không tuyên bố có dự báo sẵn đúng giây 00**.
- Clock local và exchange được đối chiếu; chênh lệch quá 5 giây hoặc request clock
  quá chậm thì từ chối. Context thiếu/invalid/schema không khớp thì không dự báo.
- Không ghi bù dự báo cho giờ đã lỡ; không dùng archive/warehouse để tạo dự báo hồi cứu.
- Label lấy lần đầu từ REST sau khi target đóng ít nhất 60 giây; lưu riêng, không
  sửa dự báo hoặc thay reference bằng dữ liệu được tải sau này.
- Không có chấm MAE giữa kỳ trong runner; `status` chỉ hiện thời gian và số record.

Kết thúc kỳ, job tự thu label còn thiếu và chấm một lần:

```text
Relative MAE = sum(abs(actual_return - predicted_return)) / sum(abs(actual_return))
coverage     = số dự báo có label / 720
```

Coverage tối thiểu 95% (ít nhất 684/720 giờ). Thiếu nhiều hơn →
`inconclusive_coverage`, dù ratio nhìn đẹp. Có dự báo nhưng chưa có label thì đợi
thu label, không âm thầm bỏ những giờ đó. Báo toàn bộ target thiếu và cả MAE model,
MAE baseline, Relative MAE, số mẫu. Ratio dùng mẫu ghép cặp; coverage chưa chứng minh
các giờ thiếu là ngẫu nhiên. Nếu baseline MAE bằng 0 thì không kết luận đạt.
Không tự promote, không giao dịch, không đổi classifier ngày/API forecast sản phẩm.

Dữ liệu 2026 đã xem trước đây không được dùng lại làm unseen test. Kỳ mới này xảy
ra sau lúc khóa candidate, dù vẫn nằm trong năm 2026. Một kỳ 30 ngày vẫn chỉ phản
ánh khoảng thị trường đó; `target_met` không phải bằng chứng PnL hoặc hiệu quả ở mọi regime.

## 2. Lưu trữ và tính bất biến

Study local:
`data/models/hourly-future/325769b1-55a7-41d2-b150-25ee5741a8b6/`.

Plan SHA-256:
`a5111ce4ba49863ac46984df241dcf87f833878a629b8d014c51dda7eb135d68`.

Artifact gồm:

- `plan.json`: protocol có digest; hash mọi file code/candidate được khóa, phiên bản Python/dependency.
- `frozen/`: code riêng mà scheduler thực sự chạy; chỉnh code repo không đổi study.
- `candidate/`: bản sao model, recipe và feature schema gốc.
- `forecasts/<target_ms>.json`: predicted return, reference close, timestamp issue,
  toàn bộ 169 kline input, digest input, hash model và plan; không có label.
- `labels/<target_ms>.json`: nến label đầu tiên quan sát được, giờ lấy, hash record dự báo.
- `events/`: outcome từng lần chạy hoặc lỗi.
- `final_score.json`: kết quả cuối ghi một lần khi đủ điều kiện.

Record được serialize/flush/fsync rồi publish atomic bằng hard link exclusive;
file đã có sẽ không bị ghi đè, kể cả khi retry. File read-only và digest được kiểm
khi đọc; worker dùng lock để tránh hai lần chạy đồng thời. Hash asset/runtime được
kiểm trước mỗi lần chạy. Lỗi có log; không biến lỗi thành dự báo hoặc score hợp lệ.

Đây là bất biến **ở mức ứng dụng trên máy local**. Người có quyền sửa filesystem
vẫn có thể chủ động xóa/viết lại record và hash; chưa có WORM storage hoặc bên thứ
ba xác thực timestamp. Không mô tả nó như chứng thực độc lập chống sửa lịch sử.

## 3. Lịch chạy đã cài

macOS LaunchAgent:
`~/Library/LaunchAgents/com.coinsight.hourly-future.325769b1-55a7-41d2-b150-25ee5741a8b6.plist`.

Chạy `tick` ở phút 01 mỗi giờ; lần chạy lúc cài đã exit 0 với `outside_window`.
Sau khi ghi final score, các tick tiếp theo chỉ trả trạng thái hoàn tất, không gọi REST.

Runtime riêng:
`data/models/hourly-runtime/venv/bin/python` (Python 3.12; XGBoost 3.0.5).

**Máy cần bật, có mạng và user đăng nhập.** LaunchAgent không giữ máy khỏi sleep.
Nếu máy thức dậy muộn, deadline vẫn được áp dụng; không coi một lần catch-up của
launchd là quyền dự báo bù. Job ở máy local chưa phải deployment trên server 24/7.

```bash
make hourly-future-status STUDY=data/models/hourly-future/325769b1-55a7-41d2-b150-25ee5741a8b6

launchctl print gui/$(id -u)/com.coinsight.hourly-future.325769b1-55a7-41d2-b150-25ee5741a8b6

# Operational smoke test, không tạo study forecast hoặc label:
data/models/hourly-runtime/venv/bin/python -m scripts.hourly_future preflight \
  --study data/models/hourly-future/325769b1-55a7-41d2-b150-25ee5741a8b6

# Bỏ lịch khi cần; giữ nguyên artifact:
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/com.coinsight.hourly-future.325769b1-55a7-41d2-b150-25ee5741a8b6.plist"
```

Stdout/stderr ở `scheduler.stdout.log`, `scheduler.stderr.log` trong study.
Sau hết kỳ có thể gọi `python -m scripts.hourly_future score --study ...`; wrapper
tự chuyển sang code đã khóa, và vẫn từ chối chấm trước khi hết kỳ.

## 4. Plan BTC-only so với BTC + ETH

Experiment:
`data/models/hourly-cross-asset/2da2f606-22ec-48be-8374-8173eaaa24b7/`.

Plan SHA-256:
`ee2264f34224928a320e3fa07ec6bd28a9d3c84b274cca43dd7977df48e7038f`.

| Fold validation | Train theo target open UTC |
| --- | --- |
| Jan–Mar 2025 | Jan–Dec 2024 |
| Apr–Jun 2025 | Apr 2024–Mar 2025 |
| Jul–Sep 2025 | Jul 2024–Jun 2025 |
| Oct–Dec 2025 | Oct 2024–Sep 2025 |

Hai nhánh train trên cùng tập timestamp đủ BTC và ETH, cùng label BTC. Nhánh gốc
compact 58 feature; nhánh kia thêm đúng 7 feature đã khóa:

1. ETH log-return 1 giờ.
2. ETH momentum 6 giờ.
3. ETH momentum 24 giờ.
4. ETH momentum 168 giờ.
5. Std ETH return 24 giờ.
6. BTC return 1 giờ trừ ETH return 1 giờ.
7. Correlation BTC–ETH return 168 giờ; window hằng số quan sát đủ thì neutral 0.

Mỗi mẫu yêu cầu context 169 nến liên tục của cả hai asset. Không fill ETH thiếu,
không dùng ETH chưa đóng. Mỗi quý phải giữ ít nhất 99% mẫu BTC validation khả dụng;
nếu không đạt thì fail thay vì thay fold hoặc chọn subset thuận lợi. Training tối
thiểu 1.000 mẫu; label train phải đóng không muộn hơn cutoff đầu validation.

Nguồn ETH: 25 ZIP tháng Dec 2023–Dec 2025 từ Binance Spot archive, mỗi ZIP kiểm
checksum chính thức và lưu manifest. Không đọc ETH/BTC target 2026. Archive là dữ
liệu hồi cứu có thể được chỉnh sửa về sau; không gọi nó là point-in-time feed.

Tham số hai nhánh là recipe trial 41, 201 cây cố định, seed 42, CPU/2 threads,
target fit nhân 10.000 rồi đổi về log-return trước khi chấm. Không early stopping,
không thử cửa sổ/seed/hyperparameter khác. Tổng cộng 8 fit, không chọn fold tốt nhất.
Report cả 4 quý và ratio gộp từ tổng absolute error trên các quý không chồng nhau.
Mỗi fold lưu model, schema, predictions và kiểm reload. Lần chạy lỗi giữ artifact
trong `attempts/`; retry dùng cùng plan và nguồn đã checksum, không ghi đè lần trước.

**2025 và recipe tham chiếu đã được dùng cho selection trước đây.** Rolling folds
giúp mô tả độ ổn định và temporal ordering, không khôi phục tính unseen của 2025.
Thêm 7 cột cũng thay không gian lấy mẫu cột của XGBoost, nên đây là so sánh hai
pipeline với cùng recipe, không chứng minh tác động thuần của ETH. Không tự promote.

LaunchAgent follow-up:
`~/Library/LaunchAgents/com.coinsight.hourly-cross-asset.2da2f606-22ec-48be-8374-8173eaaa24b7.plist`.

Job kiểm gate ở phút 10 mỗi giờ. Hiện gate đóng, trả
`waiting_for_prospective_completion`, không download hoặc train. Sau khi có
`final_score.json` hợp lệ, job tự chạy đúng experiment đã khóa; các lần sau chỉ đọc
report đã có. Nếu job tương lai chưa hoàn tất, không bỏ gate hoặc chuyển sang train.

```bash
make hourly-cross-asset-status EXPERIMENT=data/models/hourly-cross-asset/2da2f606-22ec-48be-8374-8173eaaa24b7

# Lệnh run hiện chỉ trả waiting, sau khi gate mở sẽ thực thi plan đã khóa:
data/models/hourly-runtime/venv/bin/python -m scripts.hourly_cross_asset run \
  --experiment data/models/hourly-cross-asset/2da2f606-22ec-48be-8374-8173eaaa24b7

# Bỏ lịch follow-up, giữ plan/artifact:
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/com.coinsight.hourly-cross-asset.2da2f606-22ec-48be-8374-8173eaaa24b7.plist"
```

## 5. Kiểm tra đã thực hiện

37 test qua: bộ feature cũ, publish exclusive/tamper, deadline và chống backfill,
label chưa đóng, asset thay đổi, cấm score giữa kỳ, coverage và phép tính score ghép
cặp; causal/context/gap của ETH, gate, và toàn bộ 4 fold với 8 fit/reload trên **dữ
liệu tổng hợp**. Không dùng synthetic score để suy ra hiệu quả thị trường.

Preflight REST thật thành công; hai LaunchAgent đã bootstrap và lần đầu exit 0.
Chưa có kết quả MAE tương lai hoặc BTC + ETH để báo ở thời điểm này.

```bash
data/models/hourly-runtime/venv/bin/python -m pytest \
  tests/decision/test_hourly_future.py \
  tests/decision/test_hourly_cross_asset.py \
  tests/decision/test_hourly_features.py -q
```
