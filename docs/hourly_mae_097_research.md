# Mục tiêu Relative MAE ≤ 0,97: nghiên cứu offline đang tiếp tục

**Chưa đạt mục tiêu.** Điểm tốt nhất hiện đo được trên cùng 4.416 giờ Jul–Dec 2025
là **0,992930**, cải thiện so với standalone **0,993389**, candidate CatBoost **0,994004** và winner
XGBoost **0,995654**. Đây là
selection đã xem nhiều lần, không phải unseen test. Mục tiêu 0,97 vẫn được giữ;
không đổi sang accuracy 97%, target khác, horizon khác hoặc subset giờ thuận lợi.

Kiểm toán lại candidate: đọc trực tiếp CSV của ensemble, kiểm liên tục đủ 4.416
timestamp Jul–Dec và tính lại Relative MAE **0,9929300496**. MAE cần đạt là
**0,0026713372**, so với hiện tại **0,0027344855**: còn thiếu mức giảm **2,3093%**
trên lỗi hiện tại. Một mô tả độ biến động bằng circular block bootstrap 168h,
2.000 draws, seed 42 cho percentile 2,5–97,5% khoảng **0,99000–0,99612**. Đây chỉ
là mô tả có điều kiện trên model đã chọn và mẫu đã xem; không điều chỉnh selection,
không phải khoảng đảm bảo hiệu quả tương lai. Không có bằng chứng hoàn thành 0,97.
Artifact: `hourly-goal-audit/0e5a9e2b-526e-46c3-8c73-2e83c8facffc/audit.json`.

## Candidate tốt nhất hiện có

### Bổ sung: neural network học chung tám asset

Run `hourly-pooled-sequence-research/8bd32c62-3ff6-466c-98be-e22ec5a28c87`
đã hoàn tất. Plan khóa trước fit: TCN/LSTM, BTC-only đối chứng với pool tám asset,
train 2023–2024, chọn epoch bằng BTC Jan–Jun 2025, tối đa sáu epoch. Pool có
138.992 context, loss dành tổng trọng số 50% cho BTC và 50% cho bảy asset còn lại.
Input là 169 nến đã đóng của chính asset; không thêm thông tin tương lai.

| Model | Relative MAE Jul–Dec, factor 0,5 |
| --- | ---: |
| BTC-only TCN | 0,998449 |
| BTC-only LSTM | 0,998731 |
| Tám asset TCN | 0,997438 |
| Tám asset LSTM | 0,998111 |

Factor 1 cũng đã chấm theo plan, không tốt hơn. Tất cả giữ nguyên 4.416 target
selection. Kết quả không thay thế ensemble 0,992930 và chưa đạt 0,97.

Chạy CPU hai luồng, tổng thời gian các vòng train khoảng 260 giây. Giới hạn
180 giây/model được kiểm **sau mỗi epoch**: pooled TCN kết thúc ở 193,3 giây,
không phải hard timeout. Memmap khoảng 934 MB; mẫu RSS khi chạy khoảng 1,9 GiB.
Không cần scheduler hoặc bật laptop liên tục. Đã tính lại tám bộ metric, kiểm
bốn model hash, timestamp/label của 8.760 giờ và cutoff label train của tám asset;
kết quả ở `independent_metrics_checks.json`. Reload model được kiểm trong run.
**67 test trong `tests/decision` đã qua.**

### Bổ sung: daily on-chain và exchange flows

Nguồn mới là [Coin Metrics Community BTC CSV](https://github.com/coinmetrics/data/blob/master/csv/btc.csv),
2.482.497 byte, snapshot local có SHA-256. Chỉ lấy ngày trước 2026 vào feature;
không dùng price, ROI hay label 2026. Tám chỉ số hoạt động mạng gồm active/balance
addresses, blocks, fees, hash rate, issuance, transaction/transfer counts; nhánh
mở rộng thêm exchange inflow, outflow, supply bằng đơn vị BTC. Feature gồm log,
thay đổi 1/7 ngày và chênh lệch với trung bình 30 ngày, ghép với compact58 BTC.

Plan trước fit: train 2024, hai CatBoost recipe cố định, hai nhóm feature và hai
độ trễ 48/72 giờ từ đầu ngày UTC. Availability lấy mốc muộn hơn giữa độ trễ đó
và `AssetEODCompletionTime` của nguồn. Không forward fill quá 30h, giữ nguyên
mọi target kể cả khi feature thiếu. Jan–Jun chỉ chẩn đoán, không fit model.

| Nhóm feature | Độ trễ | Relative MAE tốt nhất trong hai recipe/factor |
| --- | ---: | ---: |
| Network | 48h | 0,996415 |
| Network + exchange flows | 48h | 0,996086 |
| Network | 72h | 0,996180 |
| Network + exchange flows | 72h | **0,995623** |

Run `hourly-onchain-research/8c06b999-c26a-4426-b867-aee7ffed25c0` lưu tám model,
16 bộ metric/factor 1 và 0,5, prediction CSV và plan. Tất cả vẫn chấm đúng
4.416 giờ Jul–Dec. Không cải thiện ensemble 0,992930; chưa đạt 0,97. Đã kiểm
reload, tính lại mọi metric, hash source/model và timestamp/label gốc. **72 test
trong `tests/decision` đã qua.**

Giới hạn: CSV truy xuất hiện tại có thể chứa sửa đổi hồi cứu, đặc biệt nhãn
exchange. Completion timestamp và độ trễ không chứng minh phiên bản giá trị đó
đã tồn tại tại cutoff lịch sử. Đây là nghiên cứu hồi cứu có caveat, không phải
bằng chứng point-in-time để đưa live; kết quả âm cũng không bác bỏ mọi nguồn on-chain.

### Khả thi nguồn tin tức: chưa có kết quả model

Probe GDELT DOC `timelinevolraw`, query cố định `bitcoin`, smoothing 0, tuần
2024-01-01 đến 2024-01-08 trả HTTP 200 với resolution `hour`. Response và URL đã
lưu ở `data/models/hourly-news-feasibility`. Tuy nhiên hai lần thu toàn kỳ bắt
đầu tuần 2023-12-18 đều trả HTTP 429 ở request đầu tiên; job đã kết thúc và không
retry nền. Lỗi được lưu ở hai run `hourly-news-sources/13a14053-8f2d-42e2-a8a5-95222dc9923b`
và `231c09ed-15f8-47a8-a7ad-b3bb50835765`. Chưa có corpus đủ kỳ hoặc điểm MAE tin tức.

`scripts/fetch_hourly_news.py` có cache, quota byte/thời gian/request và giãn cách
6 giây. Bộ feature dự kiến dùng bin giờ hoàn tất cộng 2h chờ, giữ missing là
unknown; tests kiểm tương lai không đổi feature quá khứ và từ chối timestamp
không hợp lệ. Historical search index vẫn không phải bản ghi point-in-time;
không suy ra việc API trả dữ liệu lịch sử là đủ điều kiện triển khai.

Recheck: run `hourly-news-sources/cafb0829-7ec5-441f-8c64-5685538c215d` cũng kết
thúc HTTP 429 ở tuần đầu. Một probe riêng tuần 2024-01-08–2024-01-15 vẫn 429,
đã lưu response/request trong `hourly-news-feasibility/second_week_*`; như vậy
không chỉ riêng truy vấn warmup 2023 gặp lỗi. Không còn collector đang chạy.
[Thông báo chính thức GDELT](https://blog.gdeltproject.org/using-the-new-web-ngrams-dataset-to-find-relevant-coverage/)
mô tả áp lực hạ tầng và giải pháp ngrams được giới thiệu tháng 6/2026; trang này
không xác nhận corpus thay thế đủ 2024–2025 cho phép kiểm đang cần. Không tự ý
tải toàn bộ news archive hoặc mở lịch thu dữ liệu laptop.

Hiện cần nguồn lịch sử mới có timestamp/availability phù hợp hoặc phục hồi truy
cập nguồn tin tức để tiếp tục hướng thí nghiệm này. Đã hỏi người dùng về tên
dataset/URL, không yêu cầu secret. Đây là chướng ngại của hướng tiếp theo, không
phải bằng chứng mọi nguồn dữ liệu công khai đều không thể đạt 0,97; mục tiêu
vẫn chưa hoàn thành. Không tạo thêm trial chỉ để tiếp tục tìm trên cùng selection.

### Tiếp tục sau blocker: cross-venue Coinbase

Probe lại GDELT sau yêu cầu tiếp tục vẫn HTTP 429; evidence ở
`hourly-news-feasibility/348d68f4-a56a-4b60-a5f5-3f242cad0ae9`.
Đã mở hướng thông tin khác, không cần credentials: [Coinbase Exchange candles](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles).
Thu BTC-USD từ 2023-12-18 đến hết 2025: **17.875 nến**, thiếu năm giờ, 63 request
có cache, tổng source record **1.133.978 byte**. Request cách nhau ít nhất một giây,
chunk 288h, quota 10 MiB/600 giây, không scheduler. Giữ nguyên mọi target BTC.

Plan trước fit: train 2024, ba recipe Hist/CatBoost cố định, control compact58
so với compact + 13 feature Coinbase (return, momentum, volatility, range,
volume và log-price basis/change/centering). Dùng nến đã đóng cùng cutoff hoặc
trễ thêm một giờ. Basis BTC-USD/BTC-USDT chứa cả ảnh hưởng USD/USDT; không gọi
là order flow hoặc premium thuần của venue. Không fit label 2025.

| Nhánh | Relative MAE tốt nhất trong ba recipe/factor |
| --- | ---: |
| BTC-only control | 0,995083 |
| Thêm Coinbase, nến vừa đóng | **0,994684** |
| Thêm Coinbase, trễ thêm 1h | 0,995718 |

Đây là thắng nhẹ so control trong run, chưa cải thiện ensemble **0,992930** và
chưa đạt **0,97**. Tất cả 18 biến thể vẫn chấm đúng 4.416 giờ Jul–Dec. Feature
Coinbase đầy đủ ở 98,025% của 8.760 giờ validation do yêu cầu 169 nến liên tục;
những giờ thiếu dùng native missing, không loại target.

Run hoàn chỉnh `hourly-venue-research/46e16d4e-7f6e-4307-99fd-6a83a29e904f`
lưu plan, chín model, predictions, source manifest và checks. Đã kiểm reload,
tính lại 18 bộ metric, hash chín model/63 source, mọi timestamp/label gốc và
không dùng source candle 2026. **75 test trong `tests/decision` đã qua.**

Run trước `564edc3d-5fdc-4969-ba90-9e2e719e4f47` dừng do lỗi join giữ warmup rows
ngoài metadata; không có metric venue từ run đó. Đã sửa bằng reindex chính xác,
lưu failure record và chạy lại từ cache với nguyên plan tham số. Dữ liệu nguồn
là snapshot hồi cứu của exchange, không có bằng chứng chống mọi sửa đổi lịch sử;
độ trễ +1h là sensitivity, không phải xác nhận publication SLA.

### Ensemble đang giữ

Ensemble tĩnh mới đạt **0,992930** trên 4.416 giờ selection. MAE **0,002734486**,
baseline **0,002753956**, giảm lỗi **0,7070%**; chưa đạt mức giảm 3%. Cần giảm thêm
khoảng **2,3093% MAE hiện tại** để đạt 0,97. Không có candidate đạt mục tiêu để công bố.

Trọng số được fit MAE trên đúng **4.343 label Jan–Jun**, chỉ dùng label đóng ít nhất
một giờ trước cutoff đầu July. Hai trong bốn member có trọng số khác 0:

```text
return forecast = 0.3718555755 * CatBoost BTC compact58 (train 2023–2024)
                + 0.1838885790 * CatBoost BTC+ETH65   (train 2024)
```

Cả hai output trong công thức đã đổi từ bps sang raw log-return; **không nhân thêm
0,5**. BTC member là Quantile depth 6; BTC+ETH member là MAE depth 4, các recipe ở
các đợt trước. ETH-history và XGBoost-reference có trọng số 0, không cần nạp lúc
inference. Bundle local đã xuất hai model, hash, schema và coefficient, kiểm được
với `pipeline.decision.hourly_calibrated.predict_ensemble`.

| Tháng selection | Relative MAE ensemble |
| --- | ---: |
| Jul 2025 | 0,996508 |
| Aug 2025 | 0,990722 |
| Sep 2025 | 0,994467 |
| Oct 2025 | 0,997427 |
| Nov 2025 | 0,987446 |
| Dec 2025 | 0,992703 |

Trọng số không được chọn riêng theo tháng hoặc fit label Jul–Dec. Đây vẫn là
selection đã xem; thắng 6/6 tháng không thay thế yêu cầu ≤0,97 hoặc unseen test.

### Standalone tốt nhất trước bước calibration

Đối chứng train history mới tìm được candidate tốt hơn:

- CatBoost 1.2.8, `Quantile:alpha=0.5`, 600 iterations, depth 6, learning rate 0,025,
  L2 leaf 50, seed 42; CPU/2 threads.
- **BTC compact 58 feature**, không cần ETH ở inference.
- Train **2023–2024, 17.374 mẫu**; không early stopping hoặc fit label 2025.
- Prediction raw-return = output bps /10.000 × **0,5**; cùng một model/factor trên
  toàn bộ selection, không chọn model theo tháng sau khi xem label.

| Metric | Jan–Jun 2025 | Jul–Dec 2025 |
| --- | ---: | ---: |
| N | 4.344 | 4.416 |
| MAE model | 0,003364534 | 0,002735750 |
| MAE zero-return | 0,003384095 | 0,002753956 |
| Relative MAE | 0,994220 | **0,993389** |

Giảm lỗi selection **0,6611%** so baseline, vẫn dưới mục tiêu **3%**. Cần giảm
thêm khoảng **2,3545% MAE của candidate mới** để đạt 0,97 trên đúng mẫu này.

| Tháng selection | Relative MAE candidate mới |
| --- | ---: |
| Jul 2025 | 0,996120 |
| Aug 2025 | 0,991405 |
| Sep 2025 | 0,995807 |
| Oct 2025 | 0,995400 |
| Nov 2025 | 0,989467 |
| Dec 2025 | 0,993899 |

Thắng baseline ở 6/6 tháng đã xem là mô tả, không phải sáu phép thử độc lập hoặc
kiểm chứng ngoài mẫu. Không biến nó thành tiêu chí thay thế ngưỡng 0,97.

### Candidate tham chiếu ở đợt nghiên cứu đầu

- CatBoost 1.2.8, MAE loss, 600 iterations, depth 4, learning rate 0,03, L2 leaf 20.
- Compact BTC 58 feature + 7 feature ETH đã định nghĩa trước đó.
- Train trên 8.784 target giờ của 2024; không early stopping hoặc fit label selection.
- Target fit tính bps; inference đổi về log-return và nhân hệ số **0,5** để co về 0.
  Hệ số 1 và 0,5 được khóa trước fit, không chọn riêng cho từng giờ/tháng.
- Scaler của các mô hình linear chỉ fit train. CatBoost này không dùng scaler.

| Metric | Jan–Jun 2025 | Jul–Dec 2025 |
| --- | ---: | ---: |
| N | 4.344 | 4.416 |
| MAE model | 0,003365582 | 0,002737442 |
| MAE zero-return | 0,003384095 | 0,002753956 |
| Relative MAE | 0,994530 | **0,994004** |

Giảm lỗi so zero-return ở selection: **0,5996%**, chưa phải 3%. Để đạt 0,97 trên
đúng mẫu này cần MAE ≤ **0,002671337**, tức giảm thêm khoảng **2,415% MAE của
candidate hiện tại**.

| Tháng selection | Relative MAE candidate |
| --- | ---: |
| Jul 2025 | 0,997853 |
| Aug 2025 | 0,991890 |
| Sep 2025 | 0,994690 |
| Oct 2025 | **1,002032** |
| Nov 2025 | 0,986457 |
| Dec 2025 | 0,992683 |

Tháng Oct kém baseline. Không thay model riêng cho tháng đó sau khi nhìn kết quả;
không coi điểm gộp tốt hơn là bằng chứng ổn định ở mọi giai đoạn.

## Những gì thực sự đã chạy trong đợt này

| Phép thử | Phạm vi | Điểm selection tốt nhất |
| --- | --- | ---: |
| Model family + ETH + diễn biến trong giờ | 24 fit, 48 phương án dự báo | **0,994004** |
| Monthly refit, raw/volatility-normalized target | 96 fit theo tháng, 32 chuỗi dự báo | 0,996043 |
| Futures/spot basis và settled funding | 15 fit, 30 phương án dự báo | 0,994004, vẫn là nhánh không thêm derivatives |
| Ensemble học trọng số trên Jan–Jun | 6 phương án, chấm Jul–Dec | 0,995764 |
| OI/positioning, snapshot trễ 60 phút | 16 fit, 32 phương án | 0,994909 ở nhánh có OI |
| OI/positioning, snapshot trễ 10 phút | 16 fit, 32 phương án | 0,995070 ở nhánh có OI |
| Chuỗi raw 168 giờ: TCN/LSTM nhỏ | 4 fit, 8 phương án | 0,998434 |
| Train history dài hơn cho MAE learners | 32 fit, 64 phương án | **0,993389** |
| Scalar calibration và ensemble, label quá khứ có lag 1h | 24 phương án | **0,992930** |
| Expert volatility/trend, threshold train-only | 45 expert fit, 36 phương án | 0,993787 |
| Auxiliary ETH train, normalization causal | 12 fit, 24 phương án | 0,994154 |
| Basket 8 tài sản và pool auxiliary rộng hơn | 28 fit, 56 phương án | Nhánh mới 0,993906; không vượt baseline |
| Snapshot book-depth thật | 24 fit, 48 phương án | Nhánh có book 0,994725 |
| Refit thêm label Jan–Jun trước selection | 24 fit, 48 phương án | 0,994040 |
| Ensemble mở rộng 129 vector prediction | 6 phương án | 0,994920 |

Các phương án có dự báo tương quan hoặc trùng nhau, không phải các phép thử thống
kê độc lập. Ngân sách selection đã tăng và được báo công khai; không gọi điểm
winner là bằng chứng ngoài mẫu chưa xem. Không đọc hoặc chấm target 2026.

### Model family và intrahour

Tám recipe khóa trước: linear median regression với hai mức L1, Huber, ridge với
target train clip ±50 bps, histogram gradient boosting MAE, hai CatBoost MAE/median,
XGBoost MAE. Mỗi recipe so trên ba bộ input: BTC compact 58, thêm ETH thành 65,
thêm 20 feature trong giờ thành 85. Mỗi model báo dự báo gốc và nhân 0,5.

25 ZIP BTC 5m Dec 2023–Dec 2025 được kiểm checksum. Feature intrahour chỉ dùng
12 nến 5 phút nằm trong nến input đã đóng: return từng đoạn, first/last 30 phút,
last 15 phút, realized volatility, tỷ trọng volume muộn và actual taker-buy volume.
OHLC, tổng quote volume và trade count được đối chiếu lại với nến 1h; chỉ cho sai
số làm tròn quote volume 0,005001 USDT. Giờ thiếu/invalid không được lấp dữ liệu.
Mọi giờ validation cũ đều đủ nguồn, không bỏ mẫu.

Best theo bộ input: BTC **0,995083**, BTC + ETH **0,994004**, thêm intrahour
**0,995968**. Thông tin trong giờ chưa giúp với phạm vi recipe đã thử.

[CatBoost loss documentation](https://catboost.ai/docs/en/concepts/loss-functions-regression)
và [scikit-learn histogram boosting](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html)
là nguồn tham chiếu objective; code chạy với phiên bản đã pin trong artifact.

### Refit theo tháng

Mỗi tháng Jul–Dec fit bằng 90 hoặc 365 ngày có label trước cutoff đầu tháng.
So CatBoost MAE và histogram MAE, với/không intrahour. Với biến đổi volatility,
target chia cho std return 24 giờ causal (floor 1 bp), và loss được weight theo
scale để vẫn tương ứng raw-return MAE. Prediction đổi về raw-return trước chấm.
Không dùng label tháng đang chấm để fit hoặc chọn số cây.

### Futures và funding

50 ZIP futures BTCUSDT 1h/funding Dec 2023–Dec 2025 được kiểm checksum. Thêm 12
feature: log futures/spot basis, thay đổi/thống kê basis 24h, futures momentum,
volume tương đối, actual taker-buy imbalance, settled funding, thay đổi funding và
tuổi event. Funding chỉ được join từ event `calc_time <= input_open_time`, tức
ít nhất một giờ trước cutoff dự báo; không lấy kỳ funding tương lai.

So nhánh 65 feature, thêm derivatives thành 77, và thêm intrahour thành 97.
Best thực sự có derivatives là **0,995070**; không vượt candidate 65 feature.
Archive có thể được chỉnh sửa; timestamp causal không chứng minh feed point-in-time.
[Binance archive schema](https://github.com/binance/binance-public-data) là nguồn định dạng.

### Ensemble

Lấy các forecast đã train 2024; bỏ các vector dự báo trùng. Trọng số MAE không âm
(tổng ≤2) hoặc median linear chỉ học từ 4.344 label Jan–Jun, rồi chấm nguyên 4.416
giờ Jul–Dec. Có mean/median co 0,5 làm đối chứng. Không fit trọng số lên selection.
Kết quả vẫn không vượt candidate tốt nhất.

### OI và positioning

Đã kiểm checksum **733 archive ngày**, 210.974 snapshot từ Dec 30 2023–Dec 31 2025.
Thêm 23 feature về OI contracts/USD, thay đổi 1/6/24h, OI z-score, log long/short
ratio của top accounts/positions và toàn bộ accounts, taker ratio, spread giữa các
nhóm, tương tác OI với hướng return đã đóng. Không suy ra positioning từ OHLC.

Plan đầu dùng snapshot `create_time <= input_open_time`, cách cutoff ít nhất một
giờ. Plan riêng sau đó kiểm sensitivity trễ 10 phút; vẫn chỉ join backward và để
margin cho cửa sổ tổng hợp 5 phút. Không gọi hai giả định archive này là bằng
chứng availability point-in-time. Tài liệu thị trường và lịch sử labeling phải
được kiểm khi đưa nguồn vào live:
[Binance market data](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data).

Cả hai plan giữ đúng 8.760 giờ validation gốc. Snapshot tồn tại ở 100% giờ
validation, nhưng **99,3659% selection có đầy đủ mọi feature positioning**; một
số derived feature thiếu do source/rolling window. Tree learners xử lý NaN native,
không loại label và không fill từ tương lai. Train có snapshot ở khoảng 99,9% giờ;
coverage chi tiết theo cột được lưu trong `source_coverage.json`.

So bốn bộ input: 65 feature tham chiếu, thêm positioning thành 88, thêm funding/
basis thành 100, thêm intrahour thành 120. Mỗi bộ chạy đúng bốn recipe đã khóa và
hai factor 1/0,5. Nhánh OI tốt nhất 0,994909 (60 phút) hoặc 0,995070 (10 phút), đều
không vượt candidate cũ 0,994004; không mở thêm search trong đợt OI này.

### Raw sequence models

Đã chạy TCN và LSTM nhỏ bằng PyTorch 2.8.0 trên CPU/2 threads, BTC-only và BTC+ETH.
Mỗi input gồm 168 transition lấy từ 169 nến đã đóng, giữ nguyên chuỗi thay vì chỉ
các indicator tóm tắt. Return/body/range chuẩn hóa bằng volatility của chính context;
log volume/trades chuẩn hóa trong context; không học normalization trên toàn năm.
Target vẫn raw BTC return: loss được weight theo scale để tối ưu raw-return MAE.

Tối đa 8 epoch, patience 3, AdamW lr 0,001, seed 42. Epoch chỉ chọn trên Jan–Jun;
Jul–Dec chấm sau khi khóa checkpoint. Có checkpoint ban đầu zero-return trong
không gian lựa chọn để không ép model train kém hơn baseline. Best TCN 0,998434;
LSTM và nhánh thêm ETH không vượt điểm đó.

Kiểm 169-candle inference, mutation tương lai, gap và state reload. LSTM float32 có
khác biệt metric diagnostic tối đa 2,804e-11 khi batch cuối khác kích thước giữa
Jan–Jun-only và full validation; verifier dùng tolerance 1e-9 cho đối chiếu checkpoint.
Metric tính lại từ prediction CSV vẫn khớp ở tolerance 1e-12.

### Train history cho các mô hình MAE mới

Đã mở rộng ETH 1h thành 72 archive tháng 2020–2025, mỗi file kiểm hash. Giữ nguyên
hai bộ input compact/ETH và bốn recipe tree, chỉ đổi train start 2020/2022/2023/2024,
đều kết thúc trước 2025. Train timestamp được ghép cặp giữa hai bộ input; không
đổi mẫu validation và không early stopping. Đây là 32 fit, 64 phương án prediction.

| Train từ | Best BTC compact | Best BTC + ETH |
| --- | ---: | ---: |
| 2020 | 0,994742 | 0,995157 |
| 2022 | 0,995166 | 0,994363 |
| 2023 | **0,993389** | 0,993976 |
| 2024 | 0,995083 | 0,994004 |

Hai năm gần nhất tốt hơn một năm cho recipe winner mới. Không suy ra thêm lịch sử
luôn giúp: bắt đầu 2020 không tốt nhất. Kết quả đối chứng XGBoost cũ ưu tiên 2024
không phải kết luận chung cho mọi model family.

### Calibration tĩnh và thích nghi theo thời gian

Bốn member: BTC-history 2023, ETH-history 2023, BTC+ETH 2024, XGBoost reference.
Scalar MAE-optimal slope tính bằng weighted median của `actual/predicted`, weight
`abs(predicted)`, giới hạn [0,2]. Chỉ fit các label đóng ≥1h trước update cutoff.
Plan khóa trước 24 phương án: static slopes, daily updates theo 7/30/90/180 ngày,
static ensemble không âm tổng weight ≤2, và monthly ensemble theo 30/90/180 ngày.
Updates động blend 0,5 với calibration tĩnh để hạn chế noise.

Static BTC slope học được **0,608632** thay cho 0,5, đạt **0,993124**. Static
ensemble đạt **0,992930**, tốt nhất. Daily/monthly updates không giúp thêm. Các
updates động dùng label Jul–Dec đã đóng trước lần update tiếp theo, được ghi rõ
là prequential adaptation; không dùng label hiện tại/tương lai. Calibration tĩnh
winner không dùng bất kỳ label Jul–Dec nào để fit coefficient.

### Expert theo regime

Giữ train 2023–2024. Threshold volatility `return_std_24` và trend
`vol_normalized_momentum_24` lấy tertile trên train; không học threshold từ 2025.
Ba gate: volatility 3 nhóm, trend 3 nhóm, hoặc grid 9 nhóm. Mỗi nhóm fit expert nếu
đủ 500 mẫu, nếu thiếu thì fallback global và vẫn chấm mọi target. Ba recipe tree,
blend expert 0,5/1 và slope cố định 0,5 hoặc calibration Jan–Jun, tổng 45 expert
model và 36 phương án. Best **0,993787**, không vượt standalone hoặc ensemble.

### Transfer BTC + ETH

Khác với thêm feature ETH, ở đây ETH cung cấp **mẫu train/label phụ trước 2025**.
So BTC-only, BTC+ETH shared, và BTC+ETH có indicator asset. Compact features cùng
schema được chuẩn hóa bằng past volatility và log-activity offsets fit riêng trên
train của từng asset. Target chia causal std24, loss weight theo scale để giữ raw
MAE trong mỗi asset; prediction luôn đổi lại về **BTC raw return** trước chấm.

BTC-only có 17.374 mẫu, pooled có 34.748 mẫu, train 2023–2024. Bốn recipe tree và
hai slope tạo 12 model/24 phương án. Best pooled **0,994154**, so control BTC-only
với cùng normalization **0,994671**. Transfer giúp control một chút nhưng vẫn kém
candidate raw-feature standalone và ensemble tốt nhất. Không dùng label ETH 2025
để fit auxiliary task và không đổi denominator/số giờ chấm BTC.

### Basket và auxiliary train nhiều asset

Đã khóa thêm BNB, SOL, XRP, DOGE, ADA, LTC, cùng ETH tạo basket bảy coin ngoài BTC.
222 ZIP tháng Dec 2022–Dec 2025 được kiểm hash. Basket là nhóm cố định equal-weight
để kiểm giả thuyết, không phải chỉ số market-cap hoặc BTC dominance.

Mỗi asset có bảy feature kiểu ETH đã thử trước đó; thêm số asset quan sát được,
mean/median return, cross-sectional dispersion và breadth. Tổng bộ BTC+basket là
112 feature. Mọi feature đều từ nến đã đóng, có prefix/future-mutation checks và
không fill từ tương lai. Source coverage đầy đủ trên train/validation đã dùng.

So ba nhánh feature compact/ETH/basket và bốn pool normalized: BTC-only, tám asset
equal-weight, tám asset với 50% weight BTC, và pool BTC50 có one-hot asset. Pool có
138.992 mẫu train 2023–2024 so 17.374 BTC-only; không thêm label BTC 2025 vào pool.
Vẫn chỉ chấm BTC trên 4.416 giờ cũ, không đổi target thành return của basket.

Best basket **0,993906**; pool equal-weight **0,995018**, pool BTC50 **0,995546**,
pool có indicator **0,995246**. Chưa vượt standalone BTC hoặc ensemble hiện tại.
Tăng số mẫu tương quan từ asset khác không bảo đảm cải thiện BTC forecasting.

### Book-depth archive thật

Đã kiểm 733 đường dẫn ngày Dec 30 2023–Dec 31 2025: **732 ZIP hợp lệ, một ngày
2024-04-18 trả 404**, tổng **326.280.207 byte / 311,17 MiB**, dưới giới hạn 512 MiB.
Xử lý từng ngày rồi giữ aggregate 5 phút để tránh nạp toàn bộ raw snapshot vào RAM.

Chỉ dùng các band -5/-2/-1 và +1/+2/+5 của futures BTCUSDT. Feature là imbalance
quantity/notional, log depth, tỷ lệ giữa các band và thống kê quá khứ một giờ;
không gọi đây là actual executed order flow hoặc best-bid/ask spread.

Guard dữ liệu yêu cầu sáu band dương/hữu hạn, không có timestamp mâu thuẫn; implied
band price `notional/depth` phải nằm trong ±20% của close spot **đã đóng trước
timestamp snapshot**. Đây là kiểm lỗi gross, không phải chứng minh book chính xác.
Giữ 2.055.637/2.082.981 snapshot qua guard; một số ngày May 2025 không có snapshot
hợp lệ. Có báo cáo lỗi nguồn tương ứng trong
[Binance public-data issue](https://github.com/binance/binance-public-data/issues/431).

Aggregate 5 phút right-closed chỉ dùng event ≤ timestamp bin. Input cuối phải cách
cutoff ít nhất 10 phút, asof tolerance 15 phút; không forward-fill field invalid.
Book có mặt ở **94,7053% Jan–Jun**, **99,9094% Jul–Dec**; toàn bộ book field đủ ở
**99,8188% selection**. Mọi label BTC vẫn được chấm, tree dùng NaN native.

Hai train start 2023/2024, ba bộ ETH65/ETH+book87/market+book134 và bốn recipe tạo
24 model/48 phương án. Book history bắt đầu cuối 2023; các mẫu train trước nguồn
này giữ book missing, không dựng dữ liệu giả. Best thực sự có book **0,994725**,
không vượt candidate tốt nhất. Không dùng source 2026 hoặc đổi sang subset ngày
có book tốt để làm đẹp điểm. Archive vẫn không chứng minh live point-in-time availability.

### Thêm dữ liệu đã có trước Jul–Dec và ensemble rộng hơn

Một plan riêng chuyển Jan–Jun thành train, không tiếp tục gọi nó là validation.
Train bắt đầu 2023 hoặc 2024, chỉ nhận label đóng **≤2025-06-30 23:00 UTC**, một giờ
trước cutoff selection đầu tiên. Số mẫu 21.717 hoặc 13.127. Không early stopping,
không fit label Jul–Dec; bốn bộ compact/ETH/ETH+book/market+book và ba recipe tạo
24 fit/48 phương án. Best **0,994040**, không tốt hơn model train kết thúc 2024.

Ensemble bổ sung lấy 129 vector khác nhau của các base model **chỉ fit label trước
2025** từ những run đã có, không đưa model refit Jan–Jun vào meta-fit Jan–Jun.
Giữ 4.343 calibration label và khoảng cách publication một giờ. Sáu phương án LP,
median regression, mean/median ensemble đều chấm đủ selection; best **0,994920**.
Không thay bundle hai-member **0,992930** bằng một ensemble nhiều model kém hơn.

## Artifact và bằng chứng kiểm tra

Các run local, được gitignore:

```text
Model/5m: data/models/hourly-mae-research/10926c36-fec5-412a-9185-9d5e44e8479a
Rolling:  data/models/hourly-rolling-research/ab83fd2a-7b89-427b-93a0-e09437b03c23
Futures:  data/models/hourly-derivatives-research/627896d7-efd9-49bb-a093-da16c9f1ddaf
Ensemble: data/models/hourly-ensemble-research/4f21e99e-ddf1-491b-ba8f-c2f3389b38be
OI 60m:   data/models/hourly-positioning-research/05e363a3-74a8-4069-9a6c-5a9e407efd3e
OI 10m:   data/models/hourly-positioning-research/dd30ec2d-a98c-4a2b-83bd-3a8085dbf137
Sequence: data/models/hourly-sequence-research/4fe465ec-8f45-4ee9-9dbb-0ed0aceb656f
History:  data/models/hourly-history-research/79b7543f-114e-4e74-9560-077ad9cc191a
Calibrate:data/models/hourly-calibration-research/f9e5fc24-d0d3-442b-9133-f743dc7d5b3d
Regimes:  data/models/hourly-regime-research/94b2d2ef-e632-4def-803b-c7f1d62666d2
Transfer: data/models/hourly-transfer-research/a27b2261-05dd-4d64-92f6-60eaf74f1fc3
Market:   data/models/hourly-market-research/c7ad51cb-9676-4d8a-8b89-894a4904b469
Book:     data/models/hourly-bookdepth-research/a335d6aa-8421-4047-8349-9886b3c18443
Pre-July: data/models/hourly-recent-research/f77184d1-cb7c-4835-9659-f8e4964c8fb4
Ensemble+:data/models/hourly-ensemble-research/141fbb6d-02a9-4714-b2df-34a92c985d22
```

Mỗi run có plan trước fit, predictions, metric và code/nguồn tham chiếu. Run đầu
và run History có `selected_model.joblib`, `selected_recipe.json`: phải nạp kèm factor 0,5 và đổi
đơn vị bps /10.000; không dùng prediction thô của model như log-return.
Ensemble tốt nhất ở `Calibrate/selected_bundle/ensemble.json`, có hai member với
coefficient riêng và `target_divisor=10000`; không áp factor standalone 0,5 lên
bundle này. Inference nhận đúng 169 nến BTC và ETH trước cutoff timezone-aware,
từ chối nến target/context thiếu/hash hoặc schema sai.

Đã kiểm:

- 25 source 5m, 50 source futures/funding và model hash; nạp lại model khớp prediction.
- Tính lại metric từ toàn bộ prediction đã lưu, đối chiếu timestamp/label giữa các nhánh.
- Monthly fit: label train đóng không muộn hơn cutoff đầu tháng; kiểm đủ 96 model.
- Mutation tương lai/prefix, gap/invalid input, funding có độ trễ một giờ.
- Inference winner với đúng 169 nến BTC và ETH, không cần nến label, khớp prediction đã lưu.
- **46 tests passed** cho feature, ensemble LP, derivatives, cross-asset và safeguard đã có.

Các đợt bổ sung đã kiểm lại source/model hash, mọi prediction CSV và metadata ghép
cặp; history winner inference với đúng 169 nến BTC không có label cũng khớp.
Toàn bộ **57 test trong `tests/decision` đã qua**. Test Torch chạy trong subprocess
riêng để tránh hang native thread pools khi cùng process đã chạy HiGHS; các job
nghiên cứu thực tế vốn cũng chạy trong process riêng. Không cần train lại các run.

Đợt calibration/regime/transfer đã tính lại toàn bộ metric từ prediction lưu,
đối chiếu metadata với 8.760 giờ gốc và hash 45 expert/12 transfer model. Mọi label
được dùng ở updates calibration đều đóng trước update cutoff ít nhất 1h. Bundle
ensemble chạy lại ba forecast cuối từ 169 nến không có label khớp CSV ở tolerance
rtol 1e-8, atol 1e-12. **61 tests trong `tests/decision` đã qua** sau các bổ sung.

Các run Market/Book/Pre-July/Ensemble+ đều có `independent_metrics_checks.json`:
tính lại metric từ CSV, so metadata với mọi giờ gốc, kiểm hash source/model và cutoff
label của refit. Book dataset được kiểm lại tổng compressed bytes dưới quota; không
loại target trong các ngày nguồn lỗi. **65 tests trong `tests/decision` đã qua**
sau khi thêm basket và book-depth checks.

Không có schedule nền, không backfill vào warehouse, không đổi hourly target hoặc
bật candidate live. Mục tiêu ≤0,97 đang mở; các kết quả trên không chứng minh mọi
dữ liệu công khai đều không thể đạt mục tiêu, và cũng không cung cấp candidate đạt nó.

Môi trường nghiên cứu riêng, không thay runtime của các study cũ:

```bash
uv venv --python 3.12 data/models/hourly-research-runtime/venv
uv pip install --python data/models/hourly-research-runtime/venv/bin/python \
  -r scripts/requirements-hourly-research.txt

data/models/hourly-research-runtime/venv/bin/python -m research.hourly.research_hourly_mae \
  --source data/models/hourly-optuna/46037a7b-2793-4bf1-b0f6-306b0a2a102b \
  --cross-source data/models/hourly-cross-asset/0255e6cb-7c66-4615-acfc-e0c6a654c19c \
  --intrahour
```
