import { useEffect, useState } from 'react';
import { api } from './format.js';
import { MarketOverview } from './MarketOverview.jsx';
import { liveReadiness } from './readiness.js';
import { useLiveStream } from './useLiveStream.js';
import {
  AssetRail, ChatPanel, EvidenceCard, MetricCard, PredictionCard,
  SectionHeading, StatusBadge, age, amount, percent, price, utc,
} from './components.jsx';

const BATCH_PATHS = (symbol) => [
  `/v1/assets/${encodeURIComponent(symbol)}/snapshot`,
  `/prices/${encodeURIComponent(symbol)}?limit=90`,
  `/v1/assets/${encodeURIComponent(symbol)}/prediction`,
  '/v1/model/evaluation',
  '/v1/data-status',
];

function LivePanel({ live }) {
  const { summary, metric, connection, now } = live;
  const observed = summary?.provenance?.observed_at;
  const status = liveReadiness(live).status;
  const change = summary?.data?.change_pct;
  return <section className="branch branch-live" aria-labelledby="live-title">
    <div className="branch-heading">
      <SectionHeading eyebrow="Streaming market data" title="The market, minute by minute"
        aside={<StatusBadge status={status} />} />
      <p>Updates automatically after each minute candle closes. Check timestamps for freshness.</p>
    </div>
    <div className="metrics live-metrics" aria-label="Live metrics">
      <MetricCard label="Latest closed 1m price" value={price(summary?.data?.close_price_usdt)}
        detail={summary?.data ? `Candle ${utc(summary.data.last_candle_at, true)}` : summary?.quality?.warnings?.[0] || 'Waiting for Spark…'} />
      <MetricCard label="15-minute change" value={change == null ? '—' : percent(change)}
        tone={change == null ? '' : change >= 0 ? 'positive' : 'negative'}
        detail={summary?.data ? `${summary.data.observed_minutes}/${summary.data.expected_minutes} closed minutes` : 'No recent closed candles'} />
      <MetricCard label="15-minute quote volume" value={summary?.data ? `${amount(summary.data.volume_quote_usdt, 0)} USDT` : '—'}
        detail={observed ? `Last event ${age(observed, now)}` : 'Waiting for committed event'} />
    </div>
    <div className="stream-section">
      <SectionHeading eyebrow="Spark aggregate" title="Seven-day rolling window"
        aside={<StatusBadge status={metric?.status} />} />
      <p className="stream-intro">Configured seven-day window, sliding by one day. Full-window coverage has not been verified; event count alone does not prove completeness.</p>
      <div className="stream-grid">
        <div><span>Average candle close</span><strong>{price(metric?.data?.avg_price_usdt)}</strong></div>
        <div><span>Quote volume</span><strong>{metric?.data ? `${amount(metric.data.total_volume_quote, 0)} USDT` : '—'}</strong></div>
        <div><span>Events processed</span><strong>{amount(metric?.data?.event_count, 0)}</strong></div>
      </div>
      <p className="stream-freshness">{metric?.data?.window_start && metric?.data?.window_end
        ? `Window ${utc(metric.data.window_start, true)} → ${utc(metric.data.window_end, true)} · ` : ''}{metric?.provenance?.observed_at
        ? `Last event ${utc(metric.provenance.observed_at, true)} · ${age(metric.provenance.observed_at, now)}`
        : metric?.quality?.warnings?.[0] || 'No Spark metric available.'}</p>
    </div>
    {connection !== 'connected' && <p className="stream-warning" role="status">WebSocket {connection}; attempting to reconnect. Last received values remain visible.</p>}
  </section>;
}

function EvidenceRail({ batch, live, symbol, operations = false }) {
  const panel = operations ? 'evidence' : 'chat';
  const { snapshot, prediction, evaluation, warehouse } = batch || {};
  const { summary, metric } = live;
  const batchId = snapshot?.provenance?.batch_id || warehouse?.data?.latest_batch_id;
  return <aside className="evidence-rail" aria-label="Evidence and chat">
    <section className="evidence-panel" hidden={panel !== 'evidence'}>
      <div className="section-bar"><h2>Evidence audit</h2><span>Read-only diagnostics</span></div>
      <h3 className="evidence-group-title">Batch warehouse</h3>
      <div className="evidence-list">
        <EvidenceCard title="Load batch" envelope={warehouse} detail={warehouse?.data?.latest_batch_id
          ? `Batch #${warehouse.data.latest_batch_id} · ${warehouse.data.latest_batch_status} · ${warehouse.data.rejected_rows ?? '—'} rejected rows.` : null} />
        <EvidenceCard title="Spot daily candle" envelope={snapshot} detail={snapshot?.data
          ? `${snapshot.provenance.source} · ${snapshot.data.as_of_date} · batch #${snapshot.provenance.batch_id}.` : null} />
        <EvidenceCard title="Direction model" envelope={evaluation}
          status={evaluation?.data?.decision === 'rejected' ? 'rejected' : undefined} detail={evaluation?.data
          ? `${evaluation.data.decision} · Brier ${amount(evaluation.data.validation_brier, 4)} vs baseline ${amount(evaluation.data.baseline_validation_brier, 4)}.` : null} />
        <EvidenceCard title="Published prediction" envelope={prediction} detail={prediction?.data
          ? `${prediction.data.model_version} · target ${prediction.data.target_date}.` : null} />
      </div>
      <h3 className="evidence-group-title">Live stream</h3>
      <div className="evidence-list">
        <EvidenceCard title="Closed 1m candles" envelope={summary} detail={summary?.data
          ? `${summary.data.observed_minutes}/${summary.data.expected_minutes} in the last 15 minutes · ${utc(summary.provenance.observed_at, true)}.` : null} />
        <EvidenceCard title="Spark 7d metric" envelope={metric} detail={metric?.data
          ? `${metric.data.event_count} events · ${utc(metric.provenance.observed_at, true)}.` : null} />
      </div>
      <a className="text-link" href={batchId ? `/api/v1/lineage/batches/${batchId}` : '/api/docs'} target="_blank" rel="noopener noreferrer">
        {batchId ? `Inspect batch #${batchId} lineage ↗` : 'Open API evidence ↗'}
      </a>
      <details className="operations-detail"><summary>Stream diagnostics</summary><LivePanel live={live} /></details>
    </section>
    <div className="assistant-slot" hidden={panel !== 'chat'}><ChatPanel symbol={symbol} /></div>
  </aside>;
}

export default function App() {
  const [assets, setAssets] = useState([]);
  const [symbol, setSymbol] = useState(null);
  const [batch, setBatch] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [view, setView] = useState('overview');
  const [workspace, setWorkspace] = useState('market');
  const live = useLiveStream(symbol);

  useEffect(() => {
    let active = true;
    api('/overview').then((rows) => {
      if (!active) return;
      setAssets(rows);
      setSymbol((current) => rows.some((row) => row.symbol === current) ? current
        : rows.find((row) => row.symbol === 'BTC')?.symbol || rows[0]?.symbol || null);
      setError('');
    }).catch((reason) => { if (active) setError(`Unable to load assets: ${reason.message}`); });
    return () => { active = false; };
  }, [revision]);

  useEffect(() => {
    if (!symbol) return undefined;
    let active = true;
    setLoading(true);
    setBatch(null);
    Promise.allSettled(BATCH_PATHS(symbol).map((path) => api(path))).then((results) => {
      if (!active) return;
      const [snapshot, prices, prediction, evaluation, warehouse] = results.map((item) => item.status === 'fulfilled' ? item.value : null);
      setBatch({ snapshot, prices, prediction, evaluation, warehouse });
      const failed = results.filter((item) => item.status === 'rejected');
      setError(failed.length ? `${failed.length} batch request(s) failed; available evidence is still shown.` : '');
      setLoading(false);
    });
    return () => { active = false; };
  }, [symbol, revision]);

  const asset = assets.find((item) => item.symbol === symbol);
  return <>
    <header className="topbar">
      <div className="brand"><strong>CoinSight</strong><span>Spot desk · Beta</span></div>
      <nav className="workspace-switch" aria-label="Workspace">
        <button aria-pressed={workspace === 'market'} onClick={() => setWorkspace('market')}>Market</button>
        <button aria-pressed={workspace === 'operations'} onClick={() => setWorkspace('operations')}>Operations</button>
      </nav>
      <div className="topbar-right">
        <span className={`connection ${live.connection === 'connected' ? 'online' : 'offline'}`}>
          <i /> {live.connection === 'connected' ? 'Stream connected' : 'Stream reconnecting'}
        </span>
        {workspace === 'operations' && <a href="/api/docs" target="_blank" rel="noopener noreferrer">API</a>}
        <button className="button button-secondary" type="button" onClick={() => setRevision((value) => value + 1)} disabled={loading} title="Reload existing API data; does not start an ingestion job">Reload data</button>
      </div>
    </header>
    {error && <div className="error-banner" role="alert">{error}</div>}
    <div className={`workspace${workspace === 'operations' ? ' operations-workspace' : ''}`}>
      <AssetRail assets={assets} symbol={symbol} onSelect={setSymbol} warehouse={batch?.warehouse} />
      <main className="analysis" hidden={workspace !== 'market'}>
        <div className="analysis-heading"><div><h1>{asset?.name || symbol || 'Select a market'} <span className="asset-symbol">{symbol || '—'}</span></h1></div>
          <span className="pair-tag">{symbol ? `${symbol}USDT` : 'Spot'} · Spot</span></div>
        <nav className="view-tabs" aria-label="Analysis views">
          {[["overview", "Chart"], ["model", "Signal"]].map(([key, label]) =>
            <button key={key} aria-pressed={view === key} onClick={() => setView(key)}>{label}{key === 'live' && <i className="live-dot" />}</button>)}
        </nav>
        {view === 'overview' && <MarketOverview symbol={symbol} batch={batch} live={live} onView={setView} onEvidence={() => setWorkspace('operations')} />}
        {view === 'model' && <div className="model-view"><PredictionCard prediction={batch?.prediction} evaluation={batch?.evaluation} />
          <EvidenceCard title="Model evaluation" envelope={batch?.evaluation} status={batch?.evaluation?.data?.decision === 'rejected' ? 'rejected' : undefined}
            detail={batch?.evaluation?.data ? `Brier score ${amount(batch.evaluation.data.validation_brier, 4)} · baseline ${amount(batch.evaluation.data.baseline_validation_brier, 4)}. Lower is better.` : undefined} />
        </div>}
      </main>
      <EvidenceRail batch={batch} live={live} symbol={symbol} operations={workspace === 'operations'} />
    </div>
  </>;
}
