# Market anomaly tool — implementation report

## 1. Kết quả và giới hạn scope

Tool public hiện tại `detect_market_anomaly` đã được nâng cấp thành một support signal cho **BTC và ETH**, mỗi coin có hai model độc lập:

| Asset | Hourly | Daily |
| --- | --- | --- |
| BTC | Isolation Forest BTC/1h | Isolation Forest BTC/1d |
| ETH | Isolation Forest ETH/1h | Isolation Forest ETH/1d |

Model không trộn feature BTC với ETH. Tool không tạo lệnh BUY/SELL, không sizing vị thế và không fuse thành decision strategy. `summary.decision` cố ý là `null` trong phase này.

Đây là unsupervised anomaly detection: output nói trạng thái hiện tại khác regime train đến mức nào. Nó không phải dự báo giá, crash probability hay bằng chứng dữ liệu bị lỗi.

## 2. Flow sau thay đổi

```text
User / Analyst agent / MCP client
  → detect_market_anomaly(symbol, cutoff)
  → load active BTC|ETH / 1h bundle và 1d bundle
  → verify checksum trước khi deserialize model
  → tải đúng số nến đã đóng từ Binance cho từng frequency
  → tính causal features
  → IsolationForest.score_samples
  → so score với threshold đã khóa từ calibration
  → trả hourly + daily + feature deviations + offline diagnostics
```

`cutoff` là thời điểm quan sát. Hourly dùng giờ UTC đã đóng gần nhất; daily dùng ngày UTC đã đóng gần nhất. Source kiểm tra server clock, continuity, OHLC bounds và snapshot hash. Nếu bundle/source sai hoặc thiếu thì tool fail closed, không tự bịa kết quả.

## 3. Feature hourly

Hourly cần **170 nến liên tục**: một current return và 168 return lịch sử làm reference. Nến hiện tại được dùng làm observation nhưng mọi baseline rolling đều `.shift(1)`.

| Feature | Ý nghĩa |
| --- | --- |
| `return_z_168h` | log return 1h / volatility của 168 return trước |
| `body_z_168h` | log(close/open) / past volatility |
| `range_ratio_168h` | `(high-low)/open` chia median range 168 giờ trước |
| `volume_z_168h` | z-score `log1p(quote volume)` so với 168 giờ trước |
| `trades_z_168h` | z-score `log1p(trade_count)` so với 168 giờ trước |
| `momentum_6h_z` | momentum 6h chuẩn hóa theo past volatility × sqrt(6) |
| `volatility_ratio_6_168h` | volatility 6h hiện tại / volatility 168h quá khứ |
| `close_position` | close nằm ở đâu trong high–low range |
| `upper_wick_fraction` | tỷ lệ râu trên trong candle range |
| `lower_wick_fraction` | tỷ lệ râu dưới trong candle range |

## 4. Feature daily

Daily cần **121 nến liên tục**. Dependency dài nhất là momentum 30 ngày được so với 90 quan sát momentum quá khứ.

| Feature | Ý nghĩa |
| --- | --- |
| `return_z_30d`, `body_z_30d` | return/body ngày hiện tại so past volatility 30 ngày |
| `range_ratio_30d` | daily range so median range 30 ngày trước |
| `volume_z_30d`, `volume_z_90d` | volume bất thường ở regime ngắn và dài |
| `trades_z_30d` | số trade bất thường so 30 ngày trước |
| `momentum_7d_z`, `momentum_30d_z` | momentum 7/30 ngày so lịch sử của chính momentum đó |
| `volatility_ratio_7_30d` | volatility 7 ngày / past volatility 30 ngày |
| `volatility_ratio_30_90d` | volatility 30 ngày / past volatility 90 ngày |
| `close_position`, wick fractions | cấu trúc candle |
| `drawdown_30d`, `drawdown_90d` | khoảng cách close tới rolling high 30/90 ngày |

Giá tuyệt đối không được đưa trực tiếp vào Forest. Feature chủ yếu là return, ratio, z-score và candle shape để giảm việc model chỉ nhận ra BTC đắt hơn ETH.

## 5. Training config

Config mặc định nằm trong `pipeline/settings.yaml`:

```yaml
market_anomaly:
  symbols: [BTC, ETH]
  frequencies: [1h, 1d]
  train_start: "2020-01-01T00:00:00Z"
  calibration_start: "2025-01-01T00:00:00Z"
  test_start: "2026-01-01T00:00:00Z"
  n_estimators: 384
  max_samples: 512
  threshold_quantile: 0.99
  seed: 42
  workers: 2
```

- Train fit Forest, không dùng label.
- Calibration chỉ khóa threshold: percentile 99 của anomaly score.
- Test đứng sau calibration và chỉ dùng để báo cáo retrospective.
- `contamination=auto`; flag phục vụ thực tế dựa trên threshold calibration riêng, không dựa vào prediction mặc định của sklearn.
- `score = -model.score_samples(X)`, nên score càng lớn càng bất thường.
- p99 không có nghĩa “99% xác suất anomaly”; nó là alert budget theo distribution calibration.

## 6. Evaluation hợp lệ khi không có label

Mỗi bundle ghi `evaluation.json` với:

- sample count, score quantiles, alert count/rate;
- số alert episode và episode dài nhất;
- alert rate theo tháng để thấy threshold có ổn định qua regime hay không;
- top timestamps để manual review;
- agreement/Jaccard với robust-feature baseline — chỉ là so hai detector, **không phải accuracy**;
- future-risk usefulness: next absolute return và realized volatility sau alert so với non-alert;
- test alert rate và calibration alert rate;
- tuyên bố rõ không có precision/recall/accuracy/AUC khi chưa có ground-truth anomaly labels.

`future_volatility_lift > 1` là dấu hiệu alert có ích như risk context. Nó vẫn không chứng minh hướng giá, lợi nhuận giao dịch hay quan hệ nhân quả. Bước đúng tiếp theo là log alert prospectively và review event/data incident thực tế.

## 7. Artifact và activation

Layout:

```text
data/models/market-anomaly/
  BTC/
    1h/<version>/...
    1h/active.json
    1d/<version>/...
    1d/active.json
  ETH/
    1h/<version>/...
    1h/active.json
    1d/<version>/...
    1d/active.json
```

Một version chứa:

- `model.joblib`: Forest;
- `feature_config.json`: thứ tự feature, required candles, train median/IQR;
- `training_plan.json`: temporal boundaries, config, source digest;
- `evaluation.json`: diagnostics;
- `serving_manifest.json`: model identity/threshold/limitations;
- `artifact_checksums.json`: checksum của toàn bộ serving contract;
- `training_snapshot.csv.gz`: snapshot tái lập research;
- `train|calibration|test_scores.csv`: score audit chi tiết.

Loader verify checksum và identity asset/frequency/version trước khi load joblib. `active.json` chỉ được thay atomically sau khi bundle load/verify thành công.

## 8. Cách train bốn model

Khởi động database/migration và chắc chắn warehouse có BTC/ETH 1h + 1d trong toàn temporal range. Sau đó:

```bash
make anomaly-train-all \
  END=2026-10-27T00:00:00Z \
  VERSION=2026-10-27-v1
```

Train riêng một bundle:

```bash
make anomaly-train \
  SYMBOL=ETH \
  FREQUENCY=1d \
  END=2026-10-27T00:00:00Z \
  VERSION=2026-10-27-v1
```

Không dùng lại cùng version nếu directory đã tồn tại. Review `evaluation.json` và top alerts trước, rồi activate từng bundle:

```bash
make anomaly-activate SYMBOL=BTC FREQUENCY=1h VERSION=2026-10-27-v1
make anomaly-activate SYMBOL=BTC FREQUENCY=1d VERSION=2026-10-27-v1
make anomaly-activate SYMBOL=ETH FREQUENCY=1h VERSION=2026-10-27-v1
make anomaly-activate SYMBOL=ETH FREQUENCY=1d VERSION=2026-10-27-v1
```

Trong lượt implementation này, code và synthetic round-trip test đã chạy, nhưng **bốn artifact production chưa được tạo**: PostgreSQL ở `127.0.0.1:5432` không phản hồi và sandbox không có quyền truy cập Docker daemon. Vì tool fail closed, cần chạy lệnh trên trong môi trường của bạn trước khi `/anomaly` có thể trả score mới.

## 9. Public response contract

```json
{
  "status": "available",
  "symbol": "ETH",
  "hourly": {
    "model_version": "...",
    "score": 0.61,
    "threshold": 0.60,
    "is_anomaly": true,
    "largest_feature_deviations": []
  },
  "daily": {
    "model_version": "...",
    "score": 0.55,
    "threshold": 0.62,
    "is_anomaly": false,
    "largest_feature_deviations": []
  },
  "summary": {
    "hourly_flagged": true,
    "daily_flagged": false,
    "risk_state": "short_term_anomaly",
    "decision": null
  }
}
```

`risk_state` chỉ tóm tắt hai flag: `no_anomaly_flag`, `short_term_anomaly`, `daily_regime_anomaly`, hoặc `multi_horizon_anomaly`.

## 10. File mới

| File | Mục đích |
| --- | --- |
| `pipeline/decision/anomaly/__init__.py` | public imports của anomaly package |
| `pipeline/decision/anomaly/features.py` | feature contract causal cho 1h/1d |
| `pipeline/decision/anomaly/bundle.py` | load/verify/score/activate immutable bundle |
| `pipeline/decision/anomaly/training.py` | temporal train, calibration, test diagnostics, artifact writer |
| `pipeline/decision/anomaly/cli.py` | CLI train từ data warehouse |
| `tests/decision/forecasting/test_market_anomaly.py` | causality, gaps, artifact round-trip và checksum tests |
| `docs/market_anomaly_implementation_report.md` | report này |

## 11. File đã sửa

| File | Thay đổi / mục đích |
| --- | --- |
| `pipeline/settings.yaml`, `pipeline/settings.py` | config anomaly chung và validation fail-fast |
| `Makefile` | `anomaly-train`, `anomaly-train-all`, `anomaly-activate` |
| `warehouse_agents/market.py` | source loader generic BTC/ETH + 1h/1d; giữ wrapper legacy |
| `warehouse_agents/tools.py` | nâng cấp `detect_market_anomaly`, trả hai horizon và offline context |
| `warehouse_agents/action_contracts.py` | schema bắt buộc symbol BTC/ETH |
| `warehouse_agents/graph.py` | mô tả tool giúp LLM chọn/gọi đúng arguments |
| `warehouse_agents/gateway.py` | MCP input BTC/ETH và fail-fast bundle load |
| `warehouse_agents/desk.py` | `/anomaly BTC|ETH`, render hourly/daily |
| `app/desk_commands.py` | backend command validation BTC/ETH |
| `frontend/src/deskCommands.js` | parser/help cho `/anomaly ETH` |
| `frontend/src/responsePolicy.js` | chart score/threshold cho cả hourly và daily |
| `warehouse_agents/compose.yml` | mount bundle root read-only vào agents |
| `warehouse_agents/skills/market-brief/SKILL.md` | hướng dẫn agent về scope BTC/ETH hai horizon |
| `docs/agent_contracts.md`, `docs/code_guide.md` | cập nhật contract và trình tự đọc code |
| `tests/warehouse_agents/test_desk.py` | direct ETH anomaly contract |

## 12. Những thứ cố ý chưa làm

- Không implement decision/trading strategy.
- Không đổi anomaly thành supervised classifier khi chưa có label policy.
- Không fuse anomaly, forecast, realtime statistics thành BUY/SELL.
- Không gọi p99 là confidence/probability.
- Không loại bỏ `warehouse_agents/anomaly.py` legacy vì `model_health` còn dùng compatibility path đó.
