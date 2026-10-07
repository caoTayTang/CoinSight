import { useEffect, useRef, useState } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { predictionReadiness } from './readiness.js';
import { age, amount, api, percent, price, utc } from './format.js';

export function StatusBadge({ status = 'unavailable' }) {
  return <span className={`badge ${status}`}>{status.replaceAll('_', ' ')}</span>;
}

export function SectionHeading({ eyebrow, title, aside }) {
  return <div className="section-heading">
    <div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div>
    {aside}
  </div>;
}

export function MetricCard({ label, value, detail, tone = '' }) {
  return <article className="metric">
    <span>{label}</span><strong className={tone}>{value}</strong><small>{detail}</small>
  </article>;
}

export function EvidenceCard({ title, envelope, detail, status }) {
  return <article className="evidence-card">
    <div className="evidence-card-top"><h3>{title}</h3><StatusBadge status={status || envelope?.status} /></div>
    <p>{detail || envelope?.quality?.warnings?.[0] || 'No result available.'}</p>
  </article>;
}

export function AssetRail({ assets, symbol, onSelect, warehouse }) {
  const [search, setSearch] = useState('');
  const filtered = assets.filter((asset) => `${asset.name} ${asset.symbol}`.toLowerCase().includes(search.toLowerCase()));
  return <aside className="asset-rail" aria-label="Tracked assets">
    <div className="section-bar"><h2>Markets <span>{assets.length}</span></h2><span>Spot · USDT</span></div>
    <label className="asset-search"><span className="sr-only">Search assets</span><input type="search" placeholder="Search name or symbol…" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
    <p className="asset-caption">Daily close · USDT</p>
    <div className="asset-list">
      {assets.length === 0 && <p className="empty">No warehouse assets yet.</p>}
      {filtered.length === 0 && assets.length > 0 && <p className="empty">No matching assets.</p>}
      {filtered.map((asset) => {
        const change = asset.latest_price_usd != null && asset.previous_price_usd > 0
          ? (asset.latest_price_usd / asset.previous_price_usd - 1) * 100 : null;
        return <button key={asset.symbol} type="button" onClick={() => onSelect(asset.symbol)}
          aria-pressed={asset.symbol === symbol}
          className={`asset-card${asset.symbol === symbol ? ' selected' : ''}`}>
          <span className="asset-card-top"><span><strong>{asset.name || asset.symbol}</strong><small>{asset.symbol}</small></span>
            <span className="asset-card-price">{amount(asset.latest_price_usd)}</span></span>
          <span className="asset-card-bottom"><span className={change == null ? '' : change >= 0 ? 'positive' : 'negative'}>{change == null ? 'Change unavailable' : percent(change)}</span>
            <span>{utc(asset.latest_ts)}</span></span>
        </button>;
      })}
    </div>
    <div className="rail-footer"><span>Warehouse: {warehouse?.data?.latest_batch_status || 'unavailable'}</span>
      <small>{utc(warehouse?.data?.latest_batch_finished_at, true)}</small></div>
  </aside>;
}

export function PriceChart({ rows = [] }) {
  const candles = [...(rows || [])].reverse().filter((row) => row.price_usd != null && Number.isFinite(Number(row.price_usd)));
  if (candles.length < 2) return <div className="chart"><p className="empty">At least two daily candles are needed for a chart.</p></div>;
  const values = candles.map((row) => Number(row.price_usd));
  const low = Math.min(...values);
  const high = Math.max(...values);
  const spread = high - low || high * .01 || 1;
  const width = 800, height = 300, left = 76, right = 20, top = 22, bottom = 32;
  const x = (index) => left + index * (width - left - right) / (values.length - 1);
  const y = (value) => top + (high - value + spread * .08) / (spread * 1.16) * (height - top - bottom);
  const points = values.map((value, index) => `${x(index)},${y(value)}`).join(' ');
  const area = `${left},${height - bottom} ${points} ${width - right},${height - bottom}`;
  return <>
    <div className="chart"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Observed daily closing price chart">
      {[0, 1, 2, 3].map((index) => {
        const value = low + (high - low) * index / 3;
        return <g key={index}><line x1={left} x2={width - right} y1={y(value)} y2={y(value)} className="grid-line" />
          <text x={left - 10} y={y(value) + 4} textAnchor="end" className="axis-label">{amount(value, 0)}</text></g>;
      })}
      <polygon points={area} className="price-area" />
      <polyline points={points} className="price-line" />
    </svg></div>
    <div className="chart-caption"><span>{utc(candles[0].ts)} – {utc(candles.at(-1).ts)}</span><span>{candles.length} closed days</span></div>
  </>;
}

export function PredictionCard({ prediction, evaluation }) {
  const probability = predictionReadiness(prediction, Date.now()) ? prediction.data.probability_up : null;
  return <section className="prediction-section">
    <SectionHeading eyebrow="Daily model" title="Direction"
      aside={<span>{prediction?.data?.target_date || 'No active signal'}</span>} />
    <div className="prediction-visual">
      {probability == null ? <p className="empty">{prediction?.data ? 'Forecast expired or unavailable.' : evaluation?.data?.decision === 'rejected'
        ? 'Model below baseline. Signal withheld.'
        : prediction?.quality?.warnings?.[0] || 'No validated prediction available.'}</p> : <>
        <div className="probability-head"><strong>{Math.round(probability * 100)}% up</strong><span>target {prediction.data.target_date}</span></div>
        <div className="probability-bar"><span style={{ width: `${probability * 100}%` }} /></div>
        <div className="probability-labels"><span>Lower probability</span><span>Higher probability</span></div>
        <p className="prediction-note">Probability of a higher daily close.</p>
      </>}
    </div>
  </section>;
}

export function ChatPanel({ symbol }) {
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState('');
  const [expanded, setExpanded] = useState(false);
  const messageListRef = useRef(null);
  const composerRef = useRef(null);
  const expandButtonRef = useRef(null);

  useEffect(() => {
    if (messageListRef.current) messageListRef.current.scrollTop = messageListRef.current.scrollHeight;
  }, [messages, busy, expanded]);

  useEffect(() => {
    if (!expanded) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    composerRef.current?.focus();
    function onKeyDown(event) {
      if (event.key === 'Escape') setExpanded(false);
    }
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', onKeyDown);
      expandButtonRef.current?.focus();
    };
  }, [expanded]);

  async function submit(event) {
    event.preventDefault();
    const message = input.trim();
    if (!message || busy) return;
    setMessages((items) => [...items, { role: 'user', text: message }]);
    setInput('');
    setBusy(true);
    try {
      const result = await api('/v1/agent/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: `${message} (Selected asset: ${symbol || 'none'})` }),
      });
      setMessages((items) => [...items, { role: 'agent', text: result.answer, modelId: result.model_id, trace: result.trace }]);
    } catch (error) {
      setMessages((items) => [...items, { role: 'agent error', text: error.message }]);
    } finally {
      setBusy(false);
    }
  }

  return <>
    {expanded && <div className="chat-backdrop" onMouseDown={() => setExpanded(false)} aria-hidden="true" />}
    <section className={`chat-panel${expanded ? ' chat-expanded' : ''}`} aria-labelledby="chat-title"
      role={expanded ? 'dialog' : undefined} aria-modal={expanded ? 'true' : undefined}>
      <div className="section-bar chat-header">
        <div><h2 id="chat-title">Desk</h2><span>{symbol || 'Select a market'} · One-shot analysis</span></div>
        <button ref={expandButtonRef} className="chat-expand" type="button"
          onClick={() => setExpanded((value) => !value)} aria-label={expanded ? 'Close expanded chat' : 'Expand chat'}>
          {expanded ? 'Close ×' : 'Expand ↗'}
        </button>
      </div>
      <div ref={messageListRef} className="chat-messages" aria-live="polite" aria-relevant="additions text">
        {messages.length === 0 && <div className="desk-empty"><p>{['BTC', 'ETH', 'SOL'].includes(symbol) ? `${symbol} market brief` : 'Analysis supports BTC, ETH, SOL'}</p><div className="chat-suggestions">{['Market brief', 'Check the signal'].map((question) => <button key={question} onClick={() => { setInput(question); composerRef.current?.focus(); }}>{question}<span aria-hidden="true">↗</span></button>)}</div></div>}
        {messages.map((item, index) => <div key={index} className={`chat-bubble ${item.role}`}>
          {item.role === 'agent' ? <div className="chat-markdown"><Markdown remarkPlugins={[remarkGfm]}
            skipHtml disallowedElements={['img']}
            components={{ a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> }}>
            {item.text}
          </Markdown>{item.trace && <details className="chat-trace"><summary>Request details · {item.trace.model_calls} model call(s)</summary>
            <p>{item.trace.duration_ms} ms · {item.trace.input_tokens} input / {item.trace.output_tokens} output tokens</p>
            <ol>{item.trace.events.map((event, i) => <li key={i}>{event.kind}: {event.name} · {event.status} · {event.duration_ms} ms</li>)}</ol>
            <small>Reference: {item.trace.trace_id}</small>
            {item.modelId && <small className="chat-model-id">{item.modelId}</small>}
          </details>}</div> : item.text}
        </div>)}
        {busy && <div className="chat-bubble agent">Analyzing…</div>}
      </div>
      <form className="chat-form" onSubmit={submit}>
        <label className="sr-only" htmlFor="chat-input">Ask CoinSight</label>
        <textarea ref={composerRef} id="chat-input" value={input} onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              event.currentTarget.form.requestSubmit();
            }
          }} maxLength={2000} rows={2} placeholder={`Ask about ${symbol || 'a market'}…`} required />
        <button className="button button-primary" type="submit" disabled={busy}>Send</button>
      </form>
      <p className="chat-composer-hint">Enter to send · Shift + Enter for a new line</p>
    </section>
  </>;
}

export function Freshness({ envelope, now }) {
  return <span>{envelope?.provenance?.observed_at ? age(envelope.provenance.observed_at, now) : 'No observed event'}</span>;
}

export { age, amount, percent, price, utc };
