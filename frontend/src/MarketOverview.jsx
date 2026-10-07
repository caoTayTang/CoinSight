import { useState } from 'react';
import { PriceChart, StatusBadge, price, percent, amount, utc } from './components.jsx';
import { liveReadiness, predictionReadiness } from './readiness.js';

export function MarketOverview({ batch, live, onView, onEvidence }) {
  const [range, setRange] = useState(90);
  const data = live.summary?.data;
  const status = liveReadiness(live).status;
  const prediction = batch?.prediction;
  const current = predictionReadiness(prediction, live.now);
  const change = status === 'ready' ? data?.change_pct : null;
  return <section className="market-overview" aria-label="Market overview">
    <div className="market-quote">
      <div><span className="quote-label">Last close · 1m</span><strong>{price(data?.close_price_usdt)}</strong>
        <small>{data?.last_candle_at ? utc(data.last_candle_at, true) : 'Awaiting feed'}</small></div>
      <StatusBadge status={status} />
    </div>
    <div className="quote-stats">
      <div><span>Change · 15m</span><strong className={change == null ? '' : change >= 0 ? 'positive' : 'negative'}>{percent(change)}</strong></div>
      <div><span>Volume · 15m</span><strong>{status === 'ready' ? `${amount(data?.volume_quote_usdt, 0)} USDT` : '—'}</strong></div>
      <div><span>Daily close</span><strong>{price(batch?.snapshot?.data?.close_price_usdt)}</strong><small>{batch?.snapshot?.data?.as_of_date || 'Unavailable'}</small></div>
    </div>
    {status !== 'ready' && <p className="feed-notice">{status === 'stale' ? 'Feed delayed' : status === 'disconnected' ? 'Feed disconnected' : 'Incomplete feed'} · Last received prices shown.</p>}
    <div className="market-chart-heading"><div><h2>Price</h2><span>Daily close · USDT</span></div>
      <div className="range-control" aria-label="Chart range">{[30, 90].map((days) => <button key={days} aria-pressed={range === days} onClick={() => setRange(days)}>{days}D</button>)}</div>
    </div>
    <PriceChart rows={(batch?.prices || []).slice(0, range)} />
    <div className="signal-strip"><div><span>Daily direction</span><strong>{current ? `${Math.round(prediction.data.probability_up * 100)}% up` : 'No active signal'}</strong>
      <small>{current ? `Target ${prediction.data.target_date} UTC` : batch?.evaluation?.data?.decision === 'rejected' ? 'Model below baseline' : 'No current validated forecast'}</small></div>
      <button className="review-link" onClick={() => onView('model')}>Model details ↗</button>
    </div>
    <button className="review-link" onClick={onEvidence}>Sources & quality ↗</button>
  </section>;
}
