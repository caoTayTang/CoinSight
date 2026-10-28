import { amount, percent, utc } from '../format.js';

function money(value) { return value == null ? '—' : `${amount(value, 2)} USDT`; }

export default function TradeAnalytics({ analytics }) {
  if (!analytics) return null;
  const rows = analytics.orders || [];
  return <section className="paper-card analytics-panel">
    <div className="paper-card-head"><div><p className="eyebrow">Accepted-order diagnostics</p><h2>Useful, harmful and portfolio P&amp;L</h2>
      <p className="paper-card-copy">Usefulness scores each accepted action over its next-day forecast horizon. It is separate from realized portfolio P&amp;L.</p></div></div>
    <div className="paper-metrics compact">
      <div className="paper-metric"><span>Portfolio P&amp;L</span><strong className={analytics.portfolio_profit_loss_usdt >= 0 ? 'positive' : 'negative'}>{money(analytics.portfolio_profit_loss_usdt)}</strong></div>
      <div className="paper-metric"><span>Realized P&amp;L</span><strong>{money(analytics.portfolio_realized_pnl_usdt)}</strong></div>
      <div className="paper-metric"><span>Accepted fills</span><strong>{analytics.accepted_order_count}</strong></div>
      <div className="paper-metric"><span>Useful rate</span><strong>{analytics.useful_rate == null ? '—' : percent(analytics.useful_rate * 100)}</strong></div>
      <div className="paper-metric"><span>Useful effect</span><strong className="positive">{money(analytics.gross_useful_effect_usdt)}</strong></div>
      <div className="paper-metric"><span>Harmful effect</span><strong className="negative">−{money(analytics.gross_harmful_effect_usdt)}</strong></div>
    </div>
    {!rows.length ? <p className="paper-empty">No accepted paper orders yet.</p> : <div className="paper-table-wrap"><table className="paper-table"><thead><tr><th>Executed</th><th>Side</th><th>Asset</th><th>Outcome</th><th>Next-day effect</th><th>Actual target return</th></tr></thead><tbody>
      {rows.map((row) => <tr key={row.order_id}><td>{utc(row.executed_at, true)}</td><td>{row.side}</td><td>{row.symbol}</td>
        <td className={row.outcome === 'USEFUL' ? 'positive' : row.outcome === 'PENDING' ? '' : 'negative'}>{row.outcome}</td>
        <td>{money(row.estimated_next_day_effect_usdt)}</td><td>{row.actual_target_return == null ? '—' : percent(row.actual_target_return * 100)}</td></tr>)}
    </tbody></table></div>}
  </section>;
}
