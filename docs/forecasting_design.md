# Đề xuất thiết kế mô hình dự báo cho CoinSight

> Trạng thái: **bản đề xuất để nhóm duyệt, chưa phải contract đã chốt**
> Phạm vi: Task C — tạo dataset từ Data Warehouse, so sánh mô hình, lưu dự
> báo và chuẩn bị tích hợp API/dashboard.
> Cập nhật: 07/10/2026.

## 1. Tóm tắt quyết định đề xuất

Phiên bản đầu tiên nên giải **một bài toán duy nhất và giống nhau cho mọi mô
hình**:

> Sau khi nến giờ `t` đã đóng, dùng tối đa 168 nến giờ gần nhất của một coin để
> dự báo log-return và giá đóng cửa ở giờ `t+1`.

| Thành phần | Đề xuất V1 |
| --- | --- |
| Nguồn | `dw.fact_ohlcv_hourly`, chỉ `source_code = 'binance'` |
| Coin | BTC, ETH, SOL; chạy BTC trước để kiểm tra pipeline |
| Target chính | `log(close[t+1] / close[t])` |
| Horizon | 1 giờ |
| Lookback tối đa | 168 giờ (7 ngày) |
| Cách train | Một bộ model riêng cho mỗi coin |
| Baseline | Zero-return/persistence và rolling-mean return |
| ML | `XGBRegressor` |
| RNN | GRU và LSTM |
| Transformer | PatchTST-based và iTransformer-based |
| Output | Predicted return, predicted close, model/run metadata |
| Live metric | Chưa đưa vào model V1; dùng ở decision layer |
| Retrain ban đầu | Theo lịch mỗi tuần; chỉ promote model nếu validation tốt hơn |

Năm model chính là XGBoost, GRU, LSTM, PatchTST-based và iTransformer-based.
Baseline vẫn bắt buộc nhưng không tính vào năm model. Các horizon `T+6h`,
`T+24h` hoặc xa hơn, global model cho 20 coin và dữ liệu phút là phần mở rộng sau khi V1
chạy đúng.

```text
              Hourly OHLCV
                    ↓
            Feature engineering
                    ↓
             Sliding windows
                    ↓
       ┌────────────┼────────────┐
       ↓            ↓            ↓
    XGBoost        RNN      Transformer-based
                 ┌──┴──┐       ┌──┴──────────┐
                 ↓     ↓       ↓             ↓
                GRU   LSTM  PatchTST    iTransformer
```

## 2. Mục tiêu và phạm vi

### 2.1. Mục tiêu

1. Xây một dataset forecasting tái lập được từ Data Warehouse.
2. So sánh năm model thuộc ba họ: tree boosting, recurrent neural network và
   Transformer chuyên cho time series.
3. Đánh giá cả chất lượng dự báo, độ ổn định và chi phí vận hành.
4. Lưu được model artifact, metadata và forecast vào hệ thống.
5. Cung cấp forecast cho FastAPI/dashboard và kết hợp với live signal.

### 2.2. Không nằm trong V1

- Dự báo từng tick hoặc giao dịch tần suất cao.
- Tự động đặt lệnh mua/bán.
- Đưa raw live candle `1m` vào model khi chưa có lịch sử tương ứng.
- News, sentiment, on-chain, order book, funding rate hoặc open interest.
- Tải một model tài chính pretrained rồi dùng ngay mà không kiểm chứng domain.
- Tối ưu lợi nhuận giao dịch như mục tiêu train chính.

## 3. Dữ liệu hiện có

Nguồn train chính và chủ yếu được extract và transform từ OHLCV chính thức từ Binance Public Data:

```text
dw.fact_ohlcv_hourly
├── asset_key
├── date_key
├── time_key
├── source_key
├── open_time
├── open_price
├── high_price
├── low_price
├── close_price
├── volume_base
├── volume_quote
├── trade_count
├── batch_id
└── loaded_at
```

## 4. Forecast contract

Forecast contract phải được chốt trước khi viết model.

### 4.1. Thời điểm dự báo

Giả sử candle `10:00:00–10:59:59 UTC` đã đóng. Tại khoảng `11:00 UTC`, hệ
thống được dùng mọi dữ liệu có `event_time <= 10:59:59` để dự báo candle kết
thúc ở `11:59:59`.

Quy ước trong dataset:

```text
cutoff_time = open_time của candle t
target_time = open_time của candle t+1
```

Model chỉ chạy khi candle `t` đã đóng. Nếu muốn dự báo giữa một candle chưa
đóng thì đó là bài toán khác và cần dataset các snapshot partial-candle.

### 4.2. Target

Target chính là next-hour log-return:

```text
y[t] = ln(close[t+1] / close[t])
```

Chuyển forecast return thành forecast price:

```text
forecast_close[t+1] = close[t] × exp(predicted_return[t+1])
```

Lý do không train trực tiếp trên giá tuyệt đối trong V1:

- Mức giá thay đổi mạnh theo thời gian.
- BTC, ETH và SOL có thang giá rất khác nhau.
- Return gần với một đại lượng tương đối và dễ so sánh giữa giai đoạn hơn.
- Zero-return tạo thành một baseline rõ ràng: giá giờ sau bằng giá hiện tại.

### 4.3. Một sample

Với lookback 168:

```text
X[t] = dữ liệu từ candle t-167 đến candle t
y[t] = log-return từ close[t] đến close[t+1]
```

Lookback không phải toàn bộ training period. Hai năm dữ liệu có thể tạo hàng
nghìn sample, mỗi sample nhìn 168 giờ gần nhất(có thể tune).

## 5. Chọn mô hình

### 5.1. Baseline bắt buộc

Không được đánh giá model chỉ bằng cách so XGBoost với GRU và Transformer.
Mọi model phải so với ít nhất với hai phương pháp thống kê sau được chọn làm baseline:

1. **Persistence/zero-return**: khá hợp lí cho short term khi mà giá thường giao động quanh giá cũ

   ```text
   predicted_return = 0
   predicted_close[t+1] = close[t]
   ```

2. **Rolling-mean return**: hợp lí hơn khi longterm

   ```text
   predicted_return = mean(return của 24 hoặc 168 giờ gần nhất)
   ```

Nếu model phức tạp không thắng baseline ổn định thì kết luận đúng là model
phức tạp chưa tạo thêm giá trị, không phải tiếp tục chỉnh trên test set.

### 5.2. XGBoost

Dùng `xgboost.XGBRegressor` với objective regression. XGBoost nhận một ma trận
tabular `[samples, features]`, nên thứ tự thời gian phải được biểu diễn bằng
lag, momentum và rolling feature.

Đề xuất cấu hình khởi đầu:

```text
objective          = reg:squarederror
tree_method        = hist
n_estimators       = 300–1500, có early stopping
learning_rate      = 0.01–0.1
max_depth          = 3–8
min_child_weight   = 1–20
subsample          = 0.7–1.0
colsample_bytree   = 0.7–1.0
reg_alpha          = 0–1
reg_lambda         = 1–20
```

Không tự viết thuật toán boosting/tree. Dùng package XGBoost chính thức, tự
viết pipeline feature, time split, training/evaluation và model registry.

### 5.3. GRU và LSTM

GRU và LSTM đều là model chính. Hai model phải dùng cùng sequence, scaler,
hidden size, số layer và training budget gần tương đương để phép so sánh tập
trung vào recurrent cell.

Input:

```text
[batch_size, sequence_length=168, feature_count]
```

Kiến trúc khởi đầu:

```text
Input features
→ GRU hoặc LSTM, hidden_size 64/128, 1–2 layers
→ hidden state cuối
→ dropout
→ linear regression head
→ predicted log-return
```

Training mặc định:

```text
loss              = Huber loss
optimizer         = AdamW
learning_rate     = 1e-4 đến 3e-3
batch_size        = 64/128/256
gradient clipping = 1.0
early stopping    = 10 epoch không cải thiện validation
max_epochs        = 100
```

Không tự cài đặt công thức gate của GRU/LSTM. Dùng `torch.nn.GRU` và
`torch.nn.LSTM`, rồi tự định nghĩa regression head, training loop, checkpoint
và evaluation.

### 5.4. PatchTST-based regressor

Paper gốc: [A Time Series is Worth 64 Words: Long-term Forecasting with
Transformers](https://arxiv.org/pdf/2211.14730).

PatchTST chia chuỗi thành các patch, dùng patch làm token và dùng chung
Transformer weights giữa các channel. Patching giảm số token attention và giữ
thông tin cục bộ trong mỗi đoạn thời gian.

Cấu hình khởi đầu cho lookback 168 giờ:

```text
context_length  = 168
patch_length    = 12 hoặc 24
patch_stride    = 6 hoặc 12
d_model         = 64 hoặc 128
nhead           = 4
num_layers      = 2 hoặc 3
dim_feedforward = 128 hoặc 256
dropout         = 0.1
```

PatchTST gốc là channel-independent: representation của một channel không
trực tiếp attend sang channel khác. CoinSight lại cần một output return từ
nhiều OHLCV-derived feature, nên V1 đề xuất:

```text
13 feature channels
→ patch từng channel
→ shared PatchTST encoder
→ gom representation của các channel
→ target-specific fusion/head
→ predicted next-hour log-return
```

Phải gọi rõ model này là **PatchTST-based regressor**, không tuyên bố là tái
lập nguyên xi benchmark của paper. Backbone bám paper/official code, còn
fusion head là adapter của CoinSight để model có cùng target và nguồn thông
tin với các model còn lại. Một ablation canonical chỉ dùng lịch sử
`log_return_1h` có thể được báo cáo riêng.

### 5.5. iTransformer-based regressor

Paper gốc: [iTransformer: Inverted Transformers Are Effective for Time Series
Forecasting](https://arxiv.org/pdf/2310.06625).

iTransformer đảo vai trò token: thay vì mỗi timestamp là một token, mỗi
feature/variate là một token chứa toàn bộ lookback. Attention vì thế học quan
hệ giữa return, candle structure, volume, trade count và time feature.

```text
Input [batch, 168, 13]
→ transpose/inverted embedding
→ 13 variate tokens [batch, 13, d_model]
→ Transformer encoder giữa các variate
→ target-specific projection/head
→ predicted next-hour log-return
```

Cấu hình khởi đầu:

```text
context_length  = 168
feature_count   = 13
d_model         = 64 hoặc 128
nhead           = 4
num_layers      = 2 hoặc 3
dim_feedforward = 128 hoặc 256
dropout         = 0.1
```

V1 supervised-train từ đầu, không dùng pretrained weights. Backbone và
normalization bám paper/official implementation; output head được điều chỉnh
thành một target return và thay đổi này phải được lưu trong run metadata.

### 5.6. Điều kiện để so sánh năm model công bằng

Năm model không thể nhận ma trận có hình dạng giống hệt nhau vì inductive bias
khác nhau. Công bằng ở đây có nghĩa:

- Cùng source, coin, target, horizon, cutoff và time split.
- Cùng giới hạn thông tin tối đa 168 giờ.
- Cùng bộ feature gốc 13 chiều; XGBoost biểu diễn thành lag/rolling, các model
  sequence dùng tensor thời gian.
- Cùng validation/test và metric implementation.
- Training/tuning budget được ghi rõ, không tune một model nhiều hơn hẳn model
  khác.
- Mọi adapter khác paper gốc phải được mô tả và version hóa.

PatchTST channel-independence là ngoại lệ cần báo cáo minh bạch: fusion head
cho phép dùng nhiều channel nhưng làm model trở thành một biến thể dựa trên
PatchTST, không phải canonical PatchTST.


## 6. Feature engineering từ OHLCV

### 6.1. Nguyên tắc

1. Feature tại cutoff `t` chỉ dùng dữ liệu có timestamp `<= t`.
2. Tất cả rolling/lag được tính riêng theo `symbol` và sau khi sort thời gian.
3. Không trộn source; V1 chỉ dùng Binance Public Data.
4. Không fit scaler, clipping threshold hoặc imputer trên validation/test.
5. Không dùng candle chưa đóng.
6. Không nội suy giá qua một khoảng thiếu bằng dữ liệu tương lai.

### 6.2. Feature theo từng candle

Ký hiệu `O, H, L, C, V, N` lần lượt là open, high, low, close, quote volume
và trade count. `eps` là số dương nhỏ chỉ dùng để tránh chia cho 0.

| Feature | Công thức | Ý nghĩa |
| --- | --- | --- |
| `log_return_1h` | `ln(C[t]/C[t-1])` | Return một giờ |
| `open_close_return` | `ln(C[t]/O[t])` | Hướng tăng/giảm candle |
| `high_low_range` | `ln(H[t]/L[t])` | Biên độ candle |
| `close_position` | `(C[t]-L[t])/(H[t]-L[t]+eps)` | Close gần đỉnh hay đáy |
| `upper_wick` | `ln(H[t]/max(O[t],C[t]))` | Bóng nến trên |
| `lower_wick` | `ln(min(O[t],C[t])/L[t])` | Bóng nến dưới |
| `log_volume` | `ln(1+V[t])` | Volume đã nén thang đo |
| `volume_change` | `ln(1+V[t])-ln(1+V[t-1])` | Thay đổi volume |
| `log_trade_count` | `ln(1+N[t])` | Mức hoạt động giao dịch |


- Bóng nến trên là tỉ lệ khoảng cách giữa giá đỉnh và giá open
- Bóng nến dưới là tỉ lệ khoảng cách giữa giá đáy và giá close
Nó cho biết là giá đã từng giao động tới đoạn nào nhưng lại k thể giữ được cho tới hết phiên.

Cần có thêm volume giao dịch của coin đó vì nó có thể cho biết giá tăng hay giảm ảnh hưởng bởi số tiền đổ vào trong cùng timestamp.

Time encoding thành feature:
- dow: day of week

```text
hour_sin = sin(2π × hour_utc / 24)
hour_cos = cos(2π × hour_utc / 24)
dow_sin  = sin(2π × day_of_week / 7)
dow_cos  = cos(2π × day_of_week / 7)
```

V1 không đưa raw `date_key`, `time_key` hoặc UNIX timestamp vào model.

### 6.3. Feature cho XGBoost
- Lag: tại 1 điểm cụ thể trong quá khứ, ví dụ cutoff đang là 10h với lag = 1 thì ta tạo 1 feature ở thời điểm 9h
- Rolling: window 1 khoảng trong quá khứ thay vì từng điểm như lag, thường dùng thống kê để mô tả

XGBoost dùng trạng thái tại cutoff `t` cộng các lag/rolling summary trong tối
đa 168 giờ:

```text
Lag hours:
0, 1, 2, 3, 6, 12, 24, 48, 72, 168

Lag series chính:
log_return_1h, open_close_return, high_low_range,
log_volume, volume_change, log_trade_count

Momentum windows: giá đã thay đổi bao nhiêu trong khoảng thời gian t
6, 12, 24, 72, 168 giờ

Volatility windows:
6, 24, 72, 168 giờ — std của log_return_1h

Volume z-score windows - cho biết volume có bất thường so với gần đây k:
24, 168 giờ
```

Momentum `k` giờ có thể tính bằng:

```text
momentum_k[t] = ln(C[t] / C[t-k])
```

Không cần tạo đủ 168 cột lag liên tiếp. Các mốc có ý nghĩa giúp feature set
nhỏ hơn và XGBoost dễ tune hơn.

### 6.4. Feature cho GRU/LSTM/PatchTST/iTransformer

Mỗi timestep trong sequence V1 chứa:

```text
log_return_1h
open_close_return
high_low_range
close_position
upper_wick
lower_wick
log_volume
volume_change
log_trade_count
hour_sin
hour_cos
dow_sin
dow_cos
```

Shape một sample:

```text
[168, 13]
```

DL model được nhìn toàn bộ sequence nên V1 chưa cần nhồi thêm nhiều technical
indicator. Rolling feature có thể được thêm trong ablation sau, nhưng phải ghi
rõ nó có dùng dữ liệu nằm trước biên lookback hay không.

### 6.5. Scaling

- XGBoost không bắt buộc scale input.
- GRU/LSTM/PatchTST/iTransformer dùng scaler fit **chỉ trên training
  partition**.
- Scaler được lưu cùng artifact của từng coin/model.
- Có thể chuẩn hóa target return bằng mean/std của training target; prediction
  phải inverse-transform trước khi tính metric và ghi DB.
- Không tính mean/std bằng toàn bộ giai đoạn 2020–2026.

V1 không winsorize return mặc định. Huber loss giảm ảnh hưởng outlier cho DL;
nếu clipping được thử, ngưỡng phải học từ train và coi là một hyperparameter.

### 6.6. Missing candle và continuity gap

Không forward-fill OHLCV rồi giả vờ đó là giao dịch thật. Với V1:

1. Reindex theo lưới giờ UTC của từng coin.
2. Đánh dấu giờ thiếu.
3. Loại sample nếu khoảng `t-167 ... t+1` cắt qua một gap.
4. Báo cáo số sample bị loại theo coin và split.

Sau này có thể thêm `missing_mask`, nhưng mọi model phải nhận thông tin tương
đương và pipeline production phải tạo được mask giống lúc train.

## 7. Input/output cụ thể của từng model

### 7.1. XGBoost

```text
Input X:  float matrix [N, F_tabular]
Target y: float vector [N] — next-hour log-return
Output:   float vector [N] — predicted next-hour log-return
```

Mỗi row tương ứng một `symbol + cutoff_time`. Các feature name và thứ tự cột
phải được lưu cùng model.

### 7.2. GRU/LSTM

```text
Input X:  float tensor [N, 168, 13]
Target y: float tensor [N, 1]
Output:   float tensor [N, 1]
```

Không dùng bidirectional RNN trong V1. Bidirectional trên một sequence hoàn
toàn thuộc quá khứ không tự gây leakage, nhưng không cần thiết cho baseline
kiến trúc và làm tăng capacity.

`Để tao đọc 2 paper này xong rồi verify lại, context 2 model ở dưới nhờ AI gen`

### 7.3. PatchTST-based

```text
Input chuẩn chung:       float tensor [N, 168, 13]
Input vào patch encoder: float tensor [N, 13, 168]
Channel representations: float tensor [N, 13, D]
Output:                  float tensor [N, 1]
```

Adapter chịu trách nhiệm transpose, patching và fusion 13 channel. Số patch
phải được suy ra từ `context_length`, `patch_length`, `stride` và padding rồi
được test bằng shape assertion.

### 7.4. iTransformer-based

```text
Input chuẩn chung: float tensor [N, 168, 13]
Variate tokens:    float tensor [N, 13, D]
Output:            float tensor [N, 1]
```

Không nhầm chiều `168` timestep với `13` variate. Đây là lỗi triển khai dễ
làm model chạy nhưng attention sai trục.

### 7.5. Output nghiệp vụ chung

Sau inverse transform:

```text
symbol
cutoff_time/generated_at
target_time
horizon_hours = 1
predicted_log_return
forecast_price_usd
model_name
model_version/run_id
```

Ground truth chỉ có sau khi target candle đóng:

```text
actual_log_return
actual_close_price
absolute_error
direction_correct
evaluated_at
```

## 8. Chia dữ liệu và chống leakage

### 8.1. Split chính

Chia theo `target_time`, riêng cho từng coin:

```text
Train:      target_time < 2025-01-01 UTC
Validation: 2025-01-01 <= target_time < 2026-01-01 UTC
Test:       target_time >= 2026-01-01 UTC
```

Test kết thúc ở candle hoàn chỉnh mới nhất tại lúc đóng băng dataset. Context
của sample validation/test được phép chứa lịch sử thuộc partition trước; đó là
thông tin thực sự có sẵn tại cutoff.

Không dùng random train/test split. Khi cần cross-validation trong train, dùng
expanding/walk-forward split và gap tối thiểu bằng forecast horizon.

### 8.2. Quy trình chọn model

```text
Train folds
→ tune hyperparameter
→ validation 2025 để chọn config/checkpoint/decision threshold
→ khóa mọi quyết định
→ chạy test 2026 đúng một lần để báo cáo cuối
```

Không tiếp tục sửa feature dựa trên kết quả test. Nếu sửa, test cũ đã trở
thành validation và cần một test period mới.

### 8.3. Reproducibility

Mỗi run phải lưu:

- Git commit.
- Data cutoff và SQL/query version.
- Feature version.
- Symbol, source, lookback, horizon.
- Split boundaries.
- Hyperparameters.
- Random seed.
- Package versions.
- Scaler và feature names.
- Metrics validation/test.

DL model chạy ít nhất 3 seed và báo cáo mean ± standard deviation. XGBoost
cũng cố định seed để tái lập.

## 9. Metric và tiêu chí so sánh

### 9.1. Chất lượng dự báo

| Metric | Dùng để |
| --- | --- |
| MAE trên log-return | Metric chính, dễ so giữa coin |
| RMSE trên log-return | Phạt lỗi lớn mạnh hơn |
| MAE giá | Sai trung bình theo USD cho từng coin |
| sMAPE giá | Sai tương đối; cần báo cáo giới hạn |
| Relative MAE | `MAE_model / MAE_persistence`; `< 1` là thắng baseline |
| Directional accuracy | Đúng dấu tăng/giảm |
| Pearson/Spearman correlation | Mức đồng biến giữa predicted và actual return |

Không dùng MAPE trực tiếp trên return vì mẫu số gần 0 làm metric bất ổn.

### 9.2. Độ ổn định

- Metric riêng từng coin và macro-average ba coin.
- Metric theo tháng/quý.
- Metric trong low/high-volatility regime.
- Mean ± std qua nhiều seed.
- Tỷ lệ các period thắng persistence baseline.

### 9.3. Chi phí vận hành

- Training wall time.
- Inference latency trên CPU, batch size 1 và batch lớn.
- Số parameter với DL.
- Kích thước artifact.
- Peak RAM/VRAM nếu đo được.

### 9.4. Chọn champion

Tiêu chí chính là validation MAE của return. Một model chỉ đáng promote nếu:

1. Không tệ hơn persistence về Relative MAE.
2. Kết quả ổn định qua coin/seed, không chỉ thắng ở một giai đoạn.
3. Không có lỗi freshness/gap ở inference.
4. Latency và tài nguyên phù hợp môi trường demo.

Test set dùng để báo cáo khả năng tổng quát hóa, không dùng để chọn champion.
