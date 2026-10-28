import { useEffect, useRef, useState } from 'react';
import AnswerFeedback from './AnswerFeedback.jsx';
import AgentResponse from './AgentResponse.jsx';
import { CommandText, ComposerBackdrop } from './CommandText.jsx';
import { CoinLogo, coinName } from './coins.jsx';
import TraceView, { useOwner } from './TraceView.jsx';
import { secretLike } from './responsePolicy.js';
import { deskCommands, parseDeskInput, toolHelp } from './deskCommands.js';
import { useDeskLayout } from './useDeskLayout.js';
import DeskSessionBar from './DeskSessionBar.jsx';
import { newThreadId, rememberModel, rememberThread, runsToMessages, storedModel, storedThread } from './deskSession.js';
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

// Small coins (SHIB) need significant digits, not two decimals.
const railPrice = (value) => Number(value) < 1
  ? new Intl.NumberFormat('en-US', { maximumSignificantDigits: 4 }).format(Number(value)) : amount(value);

export function AssetRail({ assets, symbol, onSelect, warehouse }) {
  const [search, setSearch] = useState('');
  const filtered = assets.filter((asset) => `${coinName(asset.symbol, asset.name)} ${asset.symbol}`.toLowerCase().includes(search.toLowerCase()));
  return <aside className="asset-rail" aria-label="Tracked assets">
    <div className="section-bar"><h2>Markets <span>{assets.length}</span></h2><span>Spot · USDT</span></div>
    <label className="asset-search"><span className="sr-only">Search assets</span><input type="search" placeholder="Search name or symbol…" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
    <p className="asset-caption">Daily close · USDT{assets[0]?.latest_ts ? ` · ${utc(assets.find(a => a.symbol === symbol)?.latest_ts || assets[0].latest_ts)}` : ''}</p>
    <div className="asset-list">
      {assets.length === 0 && <p className="empty">No warehouse assets yet.</p>}
      {filtered.length === 0 && assets.length > 0 && <p className="empty">No matching assets.</p>}
      {filtered.map((asset) => {
        const change = asset.latest_price_usd != null && asset.previous_price_usd > 0
          ? (asset.latest_price_usd / asset.previous_price_usd - 1) * 100 : null;
        const ageDays = asset.daily_age_days == null ? null : Number(asset.daily_age_days);
        const stale = ageDays == null || ageDays > 0;
        return <button key={asset.symbol} type="button" onClick={() => onSelect(asset.symbol)}
          aria-pressed={asset.symbol === symbol}
          title={ageDays == null ? 'No daily warehouse candle' : stale ? `${ageDays} completed UTC day(s) behind` : 'Latest fully closed UTC day'}
          className={`asset-card${asset.symbol === symbol ? ' selected' : ''}${stale ? ' stale' : ''}`}>
          <CoinLogo symbol={asset.symbol}/>
          <span className="asset-row-name"><strong>{asset.symbol}<small>/USDT</small></strong><span>{coinName(asset.symbol, asset.name)}</span></span>
          <span className="asset-row-values">
            <span className="asset-card-price">{asset.latest_price_usd == null ? '—' : railPrice(asset.latest_price_usd)}</span>
            <span className={`asset-change${change == null ? ' none' : change >= 0 ? ' positive' : ' negative'}`}
              title={change == null ? 'No previous daily close to compare' : 'Change from the previous daily close'}>{change == null ? 'no data' : percent(change)}</span>
            <small className={stale ? 'asset-stale-date' : ''}>{utc(asset.latest_ts)}{stale && ageDays != null ? ` · ${ageDays}d stale` : ''}</small>
          </span>
        </button>;
      })}
    </div>
    <div className="rail-footer"><span>Warehouse: {warehouse?.data?.latest_batch_status || 'unavailable'}</span>
      <small>{utc(warehouse?.data?.latest_batch_finished_at, true)}</small></div>
  </aside>;
}

export function LiveCandleChart({ candles = [] }) {
  const [hoverIndex, setHoverIndex] = useState(null);
  const rows = (candles || []).filter((row) => row.open_price_usdt != null && row.high_price_usdt != null && row.low_price_usdt != null && row.close_price_usdt != null);
  if (rows.length < 2) return <div className="chart live-candle-chart"><p className="empty">Waiting for at least two closed one-minute candles.</p></div>;
  const values = rows.flatMap((row) => [Number(row.high_price_usdt), Number(row.low_price_usdt)]);
  const low = Math.min(...values);
  const high = Math.max(...values);
  const spread = high - low || high * .01 || 1;
  const width = 800, height = 300, left = 76, right = 20, top = 20, bottom = 74, volumeHeight = 40;
  const volumes = rows.map((row) => Number(row.volume_quote_usdt) || 0);
  const maxVolume = Math.max(...volumes, 1);
  const step = (width - left - right) / rows.length;
  const body = Math.max(3, step * .54);
  const x = (index) => left + step * index + step / 2;
  const y = (value) => top + (high - Number(value) + spread * .08) / (spread * 1.16) * (height - top - bottom);
  const activeIndex = hoverIndex ?? rows.length - 1;
  const active = rows[activeIndex];
  const activeChange = active ? (Number(active.close_price_usdt) / Number(active.open_price_usdt) - 1) * 100 : null;
  const activeUp = activeChange == null || activeChange >= 0;
  return <>
    <div className="chart-hover-bar" aria-live="polite">
      <span>{utc(active.open_time, true)}</span>
      <span>O <b>{amount(active.open_price_usdt)}</b></span>
      <span>H <b>{amount(active.high_price_usdt)}</b></span>
      <span>L <b>{amount(active.low_price_usdt)}</b></span>
      <span>C <b>{amount(active.close_price_usdt)}</b></span>
      <span className={activeUp ? 'positive' : 'negative'}>{percent(activeChange)}</span>
      <span>Vol <b>{amount(active.volume_quote_usdt, 0)} USDT</b></span>
    </div>
    <div className="chart live-candle-chart"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Live one-minute candlestick chart" onPointerLeave={() => setHoverIndex(null)}>
      {[0, 1, 2, 3].map((index) => {
        const value = low + (high - low) * index / 3;
        return <g key={index}><line x1={left} x2={width - right} y1={y(value)} y2={y(value)} className="grid-line" />
          <text x={left - 10} y={y(value) + 4} textAnchor="end" className="axis-label">{amount(value, 0)}</text></g>;
      })}
      {hoverIndex != null && <g className="chart-crosshair">
        <line x1={x(hoverIndex)} x2={x(hoverIndex)} y1={top} y2={height - bottom} />
        <line x1={left} x2={width - right} y1={y(rows[hoverIndex].close_price_usdt)} y2={y(rows[hoverIndex].close_price_usdt)} />
        <text x={width - right - 4} y={y(rows[hoverIndex].close_price_usdt) - 6} textAnchor="end">{amount(rows[hoverIndex].close_price_usdt)}</text>
      </g>}
      {rows.map((row, index) => {
        const up = Number(row.close_price_usdt) >= Number(row.open_price_usdt);
        const cx = x(index);
        const openY = y(row.open_price_usdt), closeY = y(row.close_price_usdt);
        const topY = Math.min(openY, closeY), heightY = Math.max(1, Math.abs(closeY - openY));
        return <g key={row.open_time || index} className={`${up ? 'candle up' : 'candle down'}${index === hoverIndex ? ' active' : ''}`}>
          <line x1={cx} x2={cx} y1={y(row.high_price_usdt)} y2={y(row.low_price_usdt)} />
          <rect x={cx - body / 2} y={topY} width={body} height={heightY} rx="1" />
        </g>;
      })}
      <text x={left - 10} y={height - bottom + 14 + volumeHeight / 2} textAnchor="end" className="axis-label">Vol</text>
      {rows.map((row, index) => {
        const barHeight = Math.max(1, volumes[index] / maxVolume * volumeHeight);
        const up = Number(row.close_price_usdt) >= Number(row.open_price_usdt);
        return <rect key={`vol-${index}`} className={`volume-bar ${up ? 'up' : 'down'}${index === hoverIndex ? ' active' : ''}`}
          x={x(index) - body / 2} y={height - bottom + 14 + volumeHeight - barHeight} width={body} height={barHeight} />;
      })}
      {rows.map((_row, index) => <rect key={`hit-${index}`} className="hit-zone" x={left + step * index} y={top} width={step} height={height - top - 6}
        onPointerEnter={() => setHoverIndex(index)} onPointerMove={() => setHoverIndex(index)} />)}
    </svg></div>
    <div className="chart-caption"><span>{utc(rows[0].open_time, true)} – {utc(rows.at(-1).close_time, true)}</span><span>{rows.length} closed 1m candles · hover for OHLC</span></div>
  </>;
}

export function PriceChart({ rows = [] }) {
  const [hoverIndex, setHoverIndex] = useState(null);
  const candles = [...(rows || [])].reverse().filter((row) => row.price_usd != null && Number.isFinite(Number(row.price_usd)));
  if (candles.length < 2) return <div className="chart"><p className="empty">At least two daily candles are needed for a chart.</p></div>;
  const values = candles.map((row) => Number(row.price_usd));
  const low = Math.min(...values);
  const high = Math.max(...values);
  const spread = high - low || high * .01 || 1;
  const width = 800, height = 300, left = 76, right = 20, top = 22, bottom = 32;
  const step = (width - left - right) / (values.length - 1);
  const x = (index) => left + index * step;
  const y = (value) => top + (high - value + spread * .08) / (spread * 1.16) * (height - top - bottom);
  const points = values.map((value, index) => `${x(index)},${y(value)}`).join(' ');
  const area = `${left},${height - bottom} ${points} ${width - right},${height - bottom}`;
  const activeIndex = hoverIndex ?? candles.length - 1;
  const active = candles[activeIndex];
  const previous = candles[activeIndex - 1];
  const change = previous?.price_usd ? (Number(active.price_usd) / Number(previous.price_usd) - 1) * 100 : null;
  return <>
    <div className="chart-hover-bar" aria-live="polite">
      <span>{utc(active.ts)}</span>
      <span>Close <b>{price(active.price_usd)}</b></span>
      <span className={change == null ? '' : change >= 0 ? 'positive' : 'negative'}>{change == null ? 'First point' : percent(change)}</span>
    </div>
    <div className="chart"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Observed daily closing price chart" onPointerLeave={() => setHoverIndex(null)}>
      {[0, 1, 2, 3].map((index) => {
        const value = low + (high - low) * index / 3;
        return <g key={index}><line x1={left} x2={width - right} y1={y(value)} y2={y(value)} className="grid-line" />
          <text x={left - 10} y={y(value) + 4} textAnchor="end" className="axis-label">{amount(value, 0)}</text></g>;
      })}
      <polygon points={area} className="price-area" />
      <polyline points={points} className="price-line" />
      {hoverIndex != null && <g className="chart-crosshair">
        <line x1={x(hoverIndex)} x2={x(hoverIndex)} y1={top} y2={height - bottom} />
        <line x1={left} x2={width - right} y1={y(values[hoverIndex])} y2={y(values[hoverIndex])} />
        <circle cx={x(hoverIndex)} cy={y(values[hoverIndex])} r="5" />
        <text x={width - right - 4} y={y(values[hoverIndex]) - 6} textAnchor="end">{amount(values[hoverIndex])}</text>
      </g>}
      {candles.map((_row, index) => <rect key={`hit-${index}`} className="hit-zone" x={index === 0 ? left - step / 2 : x(index) - step / 2} y={top} width={step} height={height - top - bottom}
        onPointerEnter={() => setHoverIndex(index)} onPointerMove={() => setHoverIndex(index)} />)}
    </svg></div>
    <div className="chart-caption"><span>{utc(candles[0].ts)} – {utc(candles.at(-1).ts)}</span><span>{candles.length} closed days · hover for values</span></div>
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

const CHAT_ICONS = {
  expand: 'M9 3h4v4M7 13H3V9M13 3 9 7M3 13l4-4',
  close: 'm4 4 8 8M12 4l-8 8',
};
const ChatIcon = ({d}) => <svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5"
  strokeLinecap="round" strokeLinejoin="round"><path d={CHAT_ICONS[d]}/></svg>;

// First visit: what the desk can answer, each with a question to start from.
const capabilities = (symbol) => [
  {title: 'Next-hour forecast', what: 'Expected move, and how far to trust it', question: `What is the ${symbol} forecast for the next hour?`},
  {title: 'Market brief', what: 'Price, unusual moves and the model view in one answer', question: `Give me a short ${symbol} market brief.`},
  {title: 'Data health', what: 'Missing candles, failed batches, stale tables', question: `@sre Is the ${symbol} data complete for the last 24 hours?`},
  {title: 'Model check', what: 'Has the model got worse, or the market changed?', question: 'Is the forecast model still reliable?'},
];

export function ChatPanel({ symbol }) {
  const desk=useDeskLayout();
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState('');
  const [expanded, setExpanded] = useState(false);
  const [threadId, setThreadId] = useState(() => storedThread() || newThreadId());
  const [model, setModel] = useState(() => storedModel() || 'auto');
  const messageListRef = useRef(null);
  const composerRef = useRef(null);
  const backdropRef = useRef(null);
  const owner = useOwner();
  const useCommand = token => {
    if (busy) return;
    setInput(token === '/tools' ? token : token + ' ');
    composerRef.current?.focus();
  };
  const expandButtonRef = useRef(null);

  useEffect(() => {
    if (messageListRef.current) messageListRef.current.scrollTop = messageListRef.current.scrollHeight;
  }, [messages, busy, expanded]);

  async function openThread(id) {
    setThreadId(id); rememberThread(id);
    try { setMessages(runsToMessages((await api(`/v1/agent/threads/${id}`)).runs)); }
    catch { setMessages([]); }
  }
  function newChat() { const id = newThreadId(); setThreadId(id); rememberThread(id); setMessages([]); }
  function pickModel(name) { setModel(name); rememberModel(name); }
  // Reopen the last conversation after a reload.
  useEffect(() => { if (storedThread()) openThread(storedThread()); }, []);

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

  async function submit(event, text) {
    event?.preventDefault();
    const message = (text ?? input).trim();
    if (!message || busy) return;
    if (secretLike(message)) {
      setInput('');
      setMessages(items=>[...items,{role:'agent error',text:'This message appears to contain an API key. Remove it and store keys in .env.'}]);
      return;
    }
    setMessages((items) => [...items, { role: 'user', text: message }]);
    setInput('');
    setBusy(true);
    try {
      const parsed = parseDeskInput(message, symbol);
      if (parsed.kind === 'tools') {
        setMessages((items) => [...items, {role:'agent',text:toolHelp()}]);
      } else {
        const {kind,...commandBody} = parsed;
        rememberThread(threadId);
        const result = await api('/v1/agent/command', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...commandBody, thread_id: threadId, ...(model !== 'auto' ? { model } : {}) }),
        });
        setMessages((items) => [...items, { role: 'agent', text: result.answer, commandMeta: result }]);
      }
    } catch (error) {
      setMessages((items) => [...items, { role: 'agent error', text: error.message }]);
    } finally {
      setBusy(false);
    }
  }

  return <>
    {expanded && <div className="chat-backdrop" onMouseDown={() => setExpanded(false)} aria-hidden="true" />}
    <section ref={desk.panelRef} className={`chat-panel${expanded ? ' chat-expanded' : ' chat-docked'}`} aria-labelledby="chat-title"
      onPointerMove={desk.move} onPointerUp={desk.finish} onPointerCancel={desk.finish}
      role={expanded ? 'dialog' : undefined} aria-modal={expanded ? 'true' : undefined}>
      {!expanded&&<div className="desk-dock-resizer" role="separator" aria-label="Resize docked chat" aria-orientation="vertical" aria-valuemin={340} aria-valuemax={620} aria-valuenow={desk.layout.dockWidth} tabIndex={0} onPointerDown={desk.begin} onKeyDown={desk.keyboard}/>}
      <div className="section-bar chat-header">
        <h2 id="chat-title">Assistant
          {symbol && <span className="chat-context"><CoinLogo symbol={symbol} size={16}/>{symbol}</span>}</h2>
        <div className="desk-window-controls">
        <button ref={expandButtonRef} className="chat-icon" type="button" onClick={() => setExpanded((value) => !value)}
          aria-label={expanded ? 'Close expanded chat' : 'Expand chat'} title={expanded ? 'Close' : 'Expand'}>
          <ChatIcon d={expanded ? 'close' : 'expand'}/></button>
        </div>
      </div>
      <DeskSessionBar model={model} onModel={pickModel} threadId={threadId} onOpenThread={openThread} onNewChat={newChat} busy={busy} />
      <div ref={messageListRef} className="chat-messages" aria-live="polite" aria-relevant="additions text">
        {messages.length === 0 && <div className="desk-empty">
          <p className="desk-empty-title">Ask about {['BTC', 'ETH', 'SOL'].includes(symbol) ? symbol : 'BTC'} or the data behind this dashboard</p>
          <p className="desk-empty-note">Answers come from live tools, not memory. Try one:</p>
          <div className="capabilities">{capabilities(['BTC', 'ETH', 'SOL'].includes(symbol) ? symbol : 'BTC').map(c =>
            <button key={c.title} type="button" disabled={busy} onClick={() => { setInput(c.question); composerRef.current?.focus(); }}>
              <strong>{c.title}</strong><span>{c.what}</span><q>{c.question}</q>
            </button>)}</div>
          <p className="desk-empty-note">It reads data only: it can't trade, restart services or change the warehouse.</p>
        </div>}
        {messages.map((item, index) => <div key={index} className={`chat-bubble ${item.role}`}>
          {item.role === 'agent' ? <div className="chat-markdown"><AgentResponse text={item.text} meta={item.commandMeta} onCommand={useCommand}
            onAsk={busy ? undefined : (question) => submit(null, (item.commandMeta?.command === 'sre' ? '@sre ' : '') + question)}/>{item.commandMeta && <details className="chat-trace"><summary>Command details · {item.commandMeta.command} · {item.commandMeta.llm_calls} LLM call(s)</summary>
            {item.commandMeta.task_id && <small>Task: {item.commandMeta.task_id}</small>}
            {/^[a-f0-9]{32}$/.test(item.commandMeta.trace_id||'')&&<div className="desk-trace-actions">{owner && <TraceView traceId={item.commandMeta.trace_id}/>}<button type="button" disabled={busy} onClick={()=>{setInput(`@sre Inspect trace ${item.commandMeta.trace_id}. Report observed errors and timing; distinguish suspected causes.`);composerRef.current?.focus();}}>Ask SRE about this trace</button></div>}
            <details><summary>Raw evidence JSON</summary><pre className="chat-evidence">{JSON.stringify(item.commandMeta.evidence,null,2)}</pre></details>
          </details>}<AnswerFeedback key={item.commandMeta?.run_id} runId={item.commandMeta?.run_id} initial={item.commandMeta?.rating} /></div> : <CommandText text={item.text} onCommand={useCommand}/>}
        </div>)}
        {busy && <div className="chat-bubble agent">Analyzing…</div>}
      </div>
      {/^[@/]/.test(input.trim()) && <div className="desk-command-menu" aria-label="Available commands">{deskCommands.filter(c=>c.token.startsWith(input.trim().split(/\s+/)[0].toLowerCase())).map(c=><button type="button" key={c.token} disabled={busy} onClick={()=>{setInput(c.command==='tools'?c.token:c.token+' ');composerRef.current?.focus();}}><strong>{c.token}</strong><span>{c.label}</span></button>)}</div>}
      <form className="chat-form" onSubmit={submit}>
        <label className="sr-only" htmlFor="chat-input">Ask CoinSight</label>
        <div className="composer-field"><ComposerBackdrop text={input} backdropRef={backdropRef}/>
        <textarea ref={composerRef} id="chat-input" value={input} onChange={(event) => setInput(event.target.value)}
          onScroll={(event) => { if (backdropRef.current) backdropRef.current.scrollTop = event.currentTarget.scrollTop; }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              event.currentTarget.form.requestSubmit();
            }
          }} maxLength={2000} rows={2} placeholder={`Ask about ${symbol || 'BTC'} or the warehouse…`} required /></div>
        <div className="composer-bar">
          <span className="composer-shortcuts" aria-label="Agent and tool shortcuts">{['@trade','@sre','/tools'].map(token=><button key={token} type="button" disabled={busy}
            title={deskCommands.find(c=>c.token===token)?.label} onClick={()=>{setInput(token==='/tools'?token:token+' ');composerRef.current?.focus();}}>{token}</button>)}</span>
          <button className="composer-send" type="submit" disabled={busy || !input.trim()} aria-label="Send" title="Send (Enter)">
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 13V3M3.5 7.5 8 3l4.5 4.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>
          </button>
        </div>
      </form>
    </section>
  </>;
}

export function Freshness({ envelope, now }) {
  return <span>{envelope?.provenance?.observed_at ? age(envelope.provenance.observed_at, now) : 'No observed event'}</span>;
}

export { age, amount, percent, price, utc };
