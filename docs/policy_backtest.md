# Paper-trading policy backtest

## Mục tiêu

Backtest này replay policy `daily_quantile_v1` tại từng mốc 00:00 UTC. Ở cutoff
ngày `t`, nó chỉ dùng nến đã đóng trước `t`, tạo forecast cho close của ngày kế
tiếp, rồi mô phỏng BUY/SELL/HOLD ở giá close gần nhất đã biết. Không dùng giá
target tương lai để tạo quyết định.

Mặc định lệnh chỉ chạy trên **test split** ghi trong snapshot của serving bundle.
Điều này tránh dùng lại train/validation để báo cáo hiệu quả policy. `end` là mốc
exclusive.

## Chạy

BTC, toàn bộ test split, vốn ban đầu 10,000 USDT:

```bash
make forecast-policy-backtest SYMBOL=BTC INITIAL_CASH=10000
```

ETH:

```bash
make forecast-policy-backtest SYMBOL=ETH INITIAL_CASH=10000
```

So sánh một policy config khác (file
`pipeline/decision/trading/policies/<version>.json`):

```bash
make forecast-policy-backtest \
  SYMBOL=BTC POLICY_VERSION=daily_quantile_v2 INITIAL_CASH=10000
```

Chạy một đoạn nhỏ nằm trong test split:

```bash
make forecast-policy-backtest \
  SYMBOL=BTC START=2026-08-01 END=2026-09-01 INITIAL_CASH=10000
```

Lệnh Python tương đương:

```bash
DATABASE_URL=postgresql://crypto:crypto@localhost:5432/crypto_dw \
.venv/bin/python -m pipeline.decision.cli policy-backtest \
  --symbol BTC --initial-cash 10000
```

Nếu warehouse thiếu grid cần thiết, lệnh dừng tại cutoff đầu tiên bị thiếu thay
vì âm thầm bỏ ngày. Hãy backfill range được báo rồi chạy lại.

## Kết quả

Mỗi run nằm tại:

```text
data/forecasting/policy-backtests/<SYMBOL>/<POLICY_VERSION>/<RUN_TIME>/
```

- `policy_backtest.json`: P&L, return %, maximum drawdown, turnover, số quyết
  định, benchmark buy-and-hold, ma trận hướng dự báo và metadata model/snapshot.
- `policy_equity_curve.csv`: equity, cash, position, drawdown và equity của
  buy-and-hold theo từng cutoff. Mỗi dòng còn có `decision_reasons` và
  `risk_flags` để audit nguyên nhân HOLD.
- `policy_trades.csv`: từng BUY/SELL và simulated fill sau slippage.
- `policy_direction_confusion.csv`: count và tỷ lệ của bốn trường hợp dự báo
  tăng/giảm so với hướng giá thực tế.
- `policy_hold_reasons.csv`: nguyên nhân chính và số lần HOLD.
- `policy_action_utility.csv`: tỷ lệ BUY/SELL hữu ích hoặc có hại theo biến động
  target day, đồng thời ước lượng tác động một ngày sau simulated slippage.
- `policy_observations.jsonl`: evidence forecast/statistics đã dùng ở từng ngày,
  để audit hoặc replay policy khác mà không gọi model lại.
- `policy_equity_curve.png`: biểu đồ policy so với buy-and-hold.

`total_return_percent` là phần trăm lời/lỗ từ vốn ban đầu đến final mark-to-market
equity. `excess_return_vs_buy_hold_percent` dương nghĩa là policy thắng benchmark
trong cùng khoảng thời gian. Backtest có slippage theo policy config nhưng chưa
mô phỏng exchange fee, và position còn mở ở ngày cuối được mark-to-market chứ
không bị ép bán.

`forecast_direction_diagnostics` phân loại từng forecast thành bốn trường hợp:

- `predicted_up_actual_up`
- `predicted_down_actual_up`
- `predicted_up_actual_down_or_flat`
- `predicted_down_actual_down_or_flat`

Dấu dự báo lấy từ `q50`; actual tăng khi target close lớn hơn reference close.
Giá bằng reference được xếp cùng nhóm down/flat, giống convention của evaluation
pipeline. `hold_reason_counts` đếm lý do được policy ghi lại trên mọi quyết định
HOLD; tổng các count này bằng tổng số HOLD. `hold_context_reason_counts` giữ toàn
bộ context reason nên tổng của nó có thể lớn hơn số HOLD. `hold_risk_flag_counts`
đếm các cảnh báo rủi ro đi kèm.

`policy_action_utility` đánh giá **BUY, SELL và HOLD của policy**, không chỉ dấu
raw forecast:

- BUY directionally useful khi target close tăng; SELL useful khi target close
  giảm, tức lệnh bán đã tránh được phần giảm đó.
- `profitable_after_slippage_rate` dùng simulated fill sau slippage. BUY có lợi
  khi target close cao hơn buy fill; SELL có lợi khi sell fill cao hơn target
  close.
- `estimated_next_day_effect_usdt` của SELL là avoided loss/missed gain trên số
  lượng đã bán, không phải lợi nhuận từ một short position.
- HOLD có hai context: `invested` nếu portfolio đang giữ coin và `cash` nếu
  không có position. HOLD-invested hữu ích khi giá tăng; HOLD-cash hữu ích khi
  giá giảm vì đã tránh được downside. Nếu HOLD-cash thì actual portfolio P&L
  vẫn bằng 0; đây là đánh giá quyết định tránh/mất cơ hội chứ không phải lợi
  nhuận giao dịch.
- HOLD không phát sinh fill nên các trường `*_after_slippage_rate` là `null`.

Các tỷ lệ trên chưa trừ exchange fee vì backtest hiện chưa có fee model.

Đây vẫn là research backtest: policy hiện tại có thể đã được thiết kế sau khi
nhìn kết quả test của forecast model. Muốn so sánh policy một cách khách quan,
cần đóng băng policy trước rồi đánh giá trên một prospective window mới.
