"""Export saved EDA notebook outputs into a standalone Vietnamese HTML report.

No database connection and no notebook code execution. Plotly is needed only to
build the artifact; its JavaScript is embedded for offline viewing.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from html import escape
from html.parser import HTMLParser
import json
import math
from pathlib import Path


class SafeTable(HTMLParser):
    """Retain table content, not notebook scripts, styles or external resources."""
    tags = {'table', 'thead', 'tbody', 'tr', 'th', 'td', 'caption', 'br'}

    def __init__(self):
        super().__init__()
        self.parts = []
        self.blocked = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.blocked += 1
        if not self.blocked and tag in self.tags:
            self.parts.append(f'<{tag}>')

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.blocked = max(0, self.blocked - 1)
        elif not self.blocked and tag in self.tags:
            self.parts.append(f'</{tag}>')

    def handle_data(self, data):
        if not self.blocked:
            self.parts.append(escape(data))


def source(cell):
    return ''.join(cell.get('source', []))


def saved_cell(notebook, marker):
    matches = [cell for cell in notebook['cells']
               if cell.get('cell_type') == 'code' and marker in source(cell)]
    if len(matches) != 1:
        raise ValueError(f'Expected one saved code cell matching {marker!r}')
    return matches[0]


def saved_plot(notebook, marker):
    for output in saved_cell(notebook, marker).get('outputs', []):
        plot = output.get('data', {}).get('application/vnd.plotly.v1+json')
        if plot:
            return plot
    raise ValueError(f'No saved Plotly output for {marker!r}; execute the notebook first')


def saved_tables(notebook, marker):
    tables = []
    for output in saved_cell(notebook, marker).get('outputs', []):
        html = output.get('data', {}).get('text/html', [])
        text = ''.join(html) if isinstance(html, list) else html
        if '<table' in text:
            parser = SafeTable()
            parser.feed(text)
            tables.append('<div class="table-scroll">' + ''.join(parser.parts) + '</div>')
    if not tables:
        raise ValueError(f'No saved table for {marker!r}')
    return ''.join(tables)


def derived_series(trace):
    """Compute daily returns only across consecutive days; never bridge gaps."""
    dates = trace['x']
    values = trace['y']
    returns, drawdowns = [], []
    peak = 0.0
    for index, (stamp, value) in enumerate(zip(dates, values)):
        if value is None or not math.isfinite(float(value)) or float(value) <= 0:
            drawdowns.append(None)
            continue
        value = float(value)
        peak = max(peak, value)
        drawdowns.append((value / peak - 1) * 100)
        if index and values[index - 1] is not None and float(values[index - 1]) > 0:
            delta = datetime.fromisoformat(stamp) - datetime.fromisoformat(dates[index - 1])
            if delta.total_seconds() == 86400:
                returns.append(math.log(value / float(values[index - 1])) * 100)
    return returns, drawdowns


def build_report(notebook_path: Path, output_path: Path):
    import plotly.graph_objects as go
    from plotly.offline import get_plotlyjs
    import plotly.io as pio

    raw = notebook_path.read_bytes()
    notebook = json.loads(raw)
    trend = saved_plot(notebook, 'normalized_close =')
    traces = trend['data']
    symbols = [trace['name'] for trace in traces]
    stamps = [stamp for trace in traces for stamp in trace['x']]
    generated = datetime.now(timezone.utc).isoformat(timespec='seconds')
    digest = hashlib.sha256(raw).hexdigest()

    def chart(plot, title, height=530):
        # Saved notebooks may contain templates from older Plotly versions.
        if isinstance(plot, dict):
            plot = {**plot, 'layout': {key: value for key, value in plot.get('layout', {}).items()
                                      if key != 'template'}}
        figure = go.Figure(plot)
        figure.update_layout(template='plotly_white', title=title, height=height,
                             font={'family': 'system-ui'}, margin={'l': 65, 'r': 25, 't': 65, 'b': 60})
        return pio.to_html(figure, full_html=False, include_plotlyjs=False,
                           config={'responsive': True, 'displaylogo': False, 'scrollZoom': False})

    distribution = go.Figure()
    drawdown = go.Figure()
    for trace in traces:
        returns, declines = derived_series(trace)
        distribution.add_trace(go.Histogram(x=returns, name=trace['name'], histnorm='probability density',
                                            opacity=.48, nbinsx=100))
        drawdown.add_trace(go.Scatter(x=trace['x'], y=declines, name=trace['name'], mode='lines',
                                     hovertemplate='%{x}<br>Drawdown: %{y:.2f}%<extra>%{fullData.name}</extra>'))
    distribution.update_layout(barmode='overlay', xaxis_title='Log-return một ngày (%)', yaxis_title='Mật độ')
    drawdown.update_layout(yaxis_title='Mức giảm từ đỉnh đã quan sát (%)', hovermode='x unified')

    parts = [f'''<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>CoinSight — Báo cáo EDA</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f5f7f5;color:#18382e;font:16px/1.7 system-ui,sans-serif}}
main{{max-width:1200px;margin:auto;padding:32px 24px 80px}}header,section{{background:white;border:1px solid #dbe5de;border-radius:14px;padding:28px;margin-bottom:22px}}
h1{{font-size:clamp(28px,4vw,44px);line-height:1.2}}h2{{font-size:25px}}h3{{font-size:18px}}a{{color:#006b55}}nav{{display:flex;gap:16px;flex-wrap:wrap}}code{{background:#edf3ee;padding:2px 6px;border-radius:4px;overflow-wrap:anywhere}}.notice{{background:#fff6dc;border-left:4px solid #bd8620;padding:16px}}.explain{{background:#edf6f0;padding:16px;border-radius:8px}}.table-scroll{{overflow:auto;margin:16px 0}}table{{border-collapse:collapse;font-size:13px;white-space:nowrap;width:100%}}td,th{{border-bottom:1px solid #dbe5de;padding:9px;text-align:right}}th:first-child,td:first-child{{text-align:left}}.meta{{font-size:13px;color:#526a60;overflow-wrap:anywhere}}.chart-wrap{{min-width:0}}li{{margin:6px 0}}@media(max-width:600px){{main{{padding:12px}}header,section{{padding:16px}}}}
</style><script>{get_plotlyjs()}</script></head><body><main>
<header><p>COINSIGHT · PHÂN TÍCH KHÁM PHÁ DỮ LIỆU</p><h1>Dữ liệu đang nói gì — và chưa nói được gì?</h1>
<p>Báo cáo EDA từ kết quả đã lưu trong <code>{escape(notebook_path.name)}</code>, có biểu đồ tương tác và giải thích tiếng Việt. Mở file này không cần Jupyter, database hoặc Internet.</p>
<div class="notice"><strong>Nguồn: output đã lưu trong notebook của người thực hiện EDA.</strong> Không chạy lại notebook, không kết nối PostgreSQL local, không xác minh lại dữ liệu Binance. Ngày xuất HTML không phải ngày làm mới dữ liệu.</div>
<p><strong>Coin trong biểu đồ:</strong> {escape(', '.join(symbols))}<br><strong>Khoảng ngày của biểu đồ:</strong> {escape(min(stamps)[:10])} → {escape(max(stamps)[:10])}. Độ dài từng coin có thể khác nhau.</p>
<nav><a href="#overview">Mục đích</a><a href="#coverage">Chất lượng</a><a href="#trend">Xu hướng</a><a href="#risk">Rủi ro</a><a href="#correlation">Tương quan</a><a href="#limits">Giới hạn</a><a href="#next">Tự làm lại</a></nav>
</header>''']
    parts.append('''<section id="overview"><h2>1. EDA là gì?</h2>
<p>EDA là khám phá và kiểm tra dữ liệu <strong>trước khi huấn luyện</strong>: dữ liệu có đủ không, biến động ra sao, có gì bất thường, và các coin liên hệ thế nào.</p>
<div class="explain"><strong>Ba việc khác nhau:</strong><ul><li><strong>Backfill:</strong> tải lịch sử còn thiếu vào warehouse.</li><li><strong>EDA:</strong> quan sát, kiểm tra và mô tả lịch sử.</li><li><strong>Training/backtest:</strong> học từ quá khứ rồi đánh giá dự báo trên giai đoạn chưa dùng để học.</li></ul></div>
<p>Biểu đồ đẹp hoặc correlation cao <strong>không chứng minh model dự báo tốt</strong>. Báo cáo này không chứa kết quả đánh giá model trong ảnh backtest.</p>
<p><strong>Cách đọc biểu đồ:</strong> rê chuột để xem số; kéo để zoom; nhấp đúp để khôi phục; nhấp tên coin trong chú giải để ẩn/hiện.</p></section>''')
    parts.append('<section id="coverage"><h2>2. Dữ liệu có đủ và hợp lệ không?</h2><h3>Danh mục trong output warehouse</h3><p>Bảng này có thể chứa nhiều coin và khoảng dữ liệu hơn sáu coin được chọn cho EDA. Đây không phải bản kiểm kê DB local hiện tại.</p>' +
                 saved_tables(notebook, 'asset_catalog = load_asset_catalog()') +
                 '<h3>Độ phủ của các coin được chọn và nhóm dữ liệu</h3>' + saved_tables(notebook, 'def coverage_row(') +
                 '<div class="explain"><strong>missing_candles:</strong> số nến thiếu giữa nến đầu và cuối của từng coin; không tính trước ngày niêm yết. <strong>duplicate:</strong> cùng coin/thời điểm bị lặp. <strong>invalid OHLC:</strong> giá không dương hoặc high/low không phù hợp open/close. Kiểm OHLC trong notebook chưa phải bộ kiểm tra toàn diện volume, checksum hay lineage.</div><p>Coin niêm yết muộn như SHIB có lịch sử ngắn hơn. So sánh tổng tăng trưởng giữa những khoảng khác nhau có thể gây hiểu nhầm.</p></section>')
    parts.append('<section id="trend"><h2>3. Giá tương đối: vì sao bắt đầu từ 100?</h2><p>Mỗi coin được đưa về chỉ số <code>close / close đầu tiên × 100</code>. Từ 100 lên 150 nghĩa là tăng 50%; đây không phải giá USDT. Trục log giúp quan sát khi một coin tăng nhiều lần.</p>' +
                 chart(trend, 'Diễn biến tương đối · điểm đầu mỗi coin = 100') +
                 '<div class="explain">Các coin không nhất thiết có cùng ngày bắt đầu. Muốn kết luận coin nào tăng tốt hơn trong cùng thời kỳ, cần lọc cùng khoảng ngày trước khi so sánh. Đường tăng trong quá khứ không dự báo đường tăng tương lai.</div></section>')
    parts.append('<section id="risk"><h2>4. Return, biến động và mức sụt giảm</h2><p><strong>Log-return</strong> = <code>ln(close hôm nay / close hôm trước)</code>. Với biến động nhỏ, log-return gần bằng phần trăm thay đổi thông thường. Với biến động lớn thì không được coi hai đại lượng là giống nhau.</p>' +
                 saved_tables(notebook, 'summary_rows = []') +
                 '<p><strong>annualized_volatility:</strong> độ lệch chuẩn log-return quy đổi theo 365 ngày/năm, không phải dự báo biến động chắc chắn. <strong>max_drawdown:</strong> mức sụt lớn nhất từ đỉnh trước đó; −0,8 nghĩa là giảm 80%, không phải 0,8%.</p>' +
                 chart(distribution, 'Phân bố log-return ngày · tái tính từ chỉ số giá đã lưu') +
                 '<p>Phân bố rộng hoặc đuôi dài cho thấy có những ngày biến động mạnh. Chưa đủ để khẳng định rủi ro tương lai hoặc xác suất lời/lỗ của chiến lược.</p>' +
                 chart(drawdown, 'Drawdown theo thời gian · tái tính từ chỉ số giá đã lưu') +
                 '<div class="explain">Return và drawdown có thể tính từ chuỗi giá đã chuẩn hóa vì nhân giá với một hằng số không đổi các tỷ lệ. Chỉ tính return khi hai ngày liên tiếp; không nối qua ngày bị thiếu. Không tái tạo giá USDT hay OHLC từ chỉ số này.</div></section>')
    parts.append('<section id="correlation"><h2>5. Các coin có biến động cùng nhau không?</h2><p>Heatmap dùng Pearson correlation của <strong>log-return</strong>, không dùng mức giá. Gần +1: thường biến động cùng chiều; gần 0: quan hệ tuyến tính yếu; gần −1: thường ngược chiều. Correlation không phải xác suất dự báo đúng.</p>' +
                 chart(saved_plot(notebook, 'ordered_symbols = sorted('), 'Tương quan return giữa các coin') +
                 '<h3>Số quan sát chung của từng cặp</h3>' + saved_tables(notebook, 'ordered_symbols = sorted(') +
                 '<p>Mỗi cặp có thể dùng một khoảng ngày khác nhau do ngày niêm yết và dữ liệu thiếu. Vì vậy, không so hệ số mà bỏ qua số quan sát chung.</p>' +
                 chart(saved_plot(notebook, 'category_returns ='), 'Tương quan return giữa các nhóm coin') +
                 '<div class="explain">Return nhóm là trung bình đều của các coin có dữ liệu tại thời điểm đó, không theo vốn hóa. Thành phần nhóm có thể đổi theo thời gian. Chỉ có các nhóm xuất hiện trong tập coin đã chọn, không đại diện toàn thị trường.</div><p>BTC và ETH tương quan cao không có nghĩa là biết ETH ngày mai từ BTC hôm nay: đây là tương quan <strong>cùng thời điểm</strong>. Muốn kiểm dự báo cần dùng độ trễ và đánh giá ngoài mẫu.</p></section>')
    parts.append('<section><h2>6. Những ngày biến động cực mạnh</h2>' + saved_tables(notebook, 'extreme_returns =') +
                 '<p>Cột <code>log_return</code> trong bảng gốc là log-return dạng thập phân. Ví dụ <code>−0,5</code> tương ứng simple return <code>exp(−0,5) − 1 ≈ −39,35%</code>, không phải luôn là −50%.</p><div class="explain">Không xóa một dòng chỉ vì biến động lớn. Cần đối chiếu sự kiện thị trường, OHLC, volume, timestamp và nguồn archive để phân biệt sự kiện thật với lỗi dữ liệu.</div></section>')
    parts.append('''<section id="limits"><h2>7. Phần chưa có và giới hạn</h2><ul>
<li>Candlestick, moving average, rolling regression và một số bộ chọn trong notebook chỉ lưu tham chiếu Jupyter widget. Bản HTML này không có đủ output OHLC để dựng lại candlestick và không tạo nến giả.</li>
<li>Rolling regression trong notebook mô tả xu hướng cửa sổ quá khứ. Chuyển slope thành 0/1 không phải classifier dự báo tương lai.</li>
<li>Hai biểu đồ return/drawdown được tái tính từ chuỗi chỉ số giá đã lưu; các bảng và heatmap còn lại là output lưu sẵn, chưa được xác minh lại bằng DB.</li>
<li>Không có train/test split hay đánh giá mô hình trong báo cáo này. Không suy ra hiệu quả giao dịch từ EDA.</li>
<li>Không có chứng nhận dữ liệu đầy đủ từ 2020 cho mọi coin; cần kiểm coverage theo từng coin và ngày niêm yết.</li>
</ul></section>
<section id="next"><h2>8. Có cần backfill máy mình không?</h2>
<p><strong>Để đọc HTML này: không cần.</strong> Dữ liệu biểu đồ và thư viện đã được nhúng trong file.</p>
<p><strong>Để tự chạy lại EDA, xác minh số liệu và làm model: cần warehouse có lịch sử đủ cho phạm vi bạn chọn.</strong> Không nhất thiết phải nạp mọi coin từ 2020 ngay.</p>
<ol><li>Bắt đầu BTC nến ngày từ một khoảng nhỏ, ví dụ 2024 trở đi.</li><li>Nạp ZIP vào staging, chạy quality/load, kiểm số dòng và khoảng thiếu.</li><li>Chạy notebook từ đầu bằng dữ liệu local; kiểm thời gian, coin và interval.</li><li>So kết quả với báo cáo này, ghi rõ khác biệt do phạm vi dữ liệu.</li><li>Sau đó mới mở rộng lịch sử/coin và tạo baseline dự báo.</li></ol>
<p><strong>Bài tập ownership:</strong> chọn một ngày BTC, tự tính return so với hôm trước; chọn một đỉnh/đáy, tự tính drawdown; chọn một cặp coin, giải thích correlation không nói được điều gì về dự báo ngày mai.</p>
</section>''')
    parts.append(f'<footer class="meta">Nguồn: {escape(notebook_path.name)} · SHA-256 notebook: {digest}<br>Xuất HTML lúc {generated}. Đây là thời điểm xuất, không phải thời điểm refresh dữ liệu.<br>Không thực thi cell notebook khi xuất. CoinSight · bản nghiên cứu, không phải khuyến nghị đầu tư.</footer></main></body></html>')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text('\n'.join(parts), encoding='utf-8')
    return output_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--notebook', type=Path, default=Path('research/eda.ipynb'))
    parser.add_argument('--output', type=Path, default=Path('frontend/public/reports/eda.html'))
    args = parser.parse_args()
    print(build_report(args.notebook, args.output))


if __name__ == '__main__':
    main()
