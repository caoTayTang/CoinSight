import { lazy, Suspense, useEffect, useState } from 'react';
import { api } from './format.js';
import { MarketOverview } from './MarketOverview.jsx';
import { DataView } from './DataView.jsx';
import { liveReadiness } from './readiness.js';
import { useLiveStream } from './useLiveStream.js';
import { CoinLogo, coinName } from './coins.jsx';
import ThemeToggle from './ThemeToggle.jsx';
import AccountMenu from './AccountMenu.jsx';
import { watchAuth } from './auth.js';

const AdminConsole = lazy(() => import('./AdminConsole.jsx'));
const TradingDashboard = lazy(() => import('./trading/TradingDashboard.jsx'));
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
  const warehouse = batch?.warehouse;
  return <aside className="evidence-rail" aria-label="Evidence and chat">
    <section className="evidence-panel" hidden={panel !== 'evidence'}>
      {operations && <DataView batch={batch} live={live} liveDetails={<LivePanel live={live} />} batchKey={warehouse?.data?.latest_batch_id} />}
    </section>
    <div className="assistant-slot"><ChatPanel symbol={symbol} /></div>
  </aside>;
}

export default function App() {
  const [assets, setAssets] = useState([]);
  const [symbol, setSymbol] = useState(null);
  const [batch, setBatch] = useState(null);
  const [loading, setLoading] = useState(false);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [view, setView] = useState('overview');
  const [workspace, setWorkspace] = useState('market');
  const live = useLiveStream(symbol);
  const [me, setMe] = useState(null);
  const owner = Boolean(me?.usage?.owner);
  const paperAccess = Boolean(me && !me.anonymous);
  useEffect(() => {
    const load = () => api('/v1/me').then(setMe).catch(() => setMe(null));
    load();
    watchAuth();
    window.addEventListener('coinsight-auth', load);
    return () => window.removeEventListener('coinsight-auth', load);
  }, []);
  useEffect(() => { if (!owner && workspace === 'admin') setWorkspace('market'); }, [owner, workspace]);
  useEffect(() => { if (!paperAccess && workspace === 'paper') setWorkspace('market'); }, [paperAccess, workspace]);

  useEffect(() => {
    let active = true;
    setOverviewLoading(true);
    api('/overview').then((all) => {
      if (!active) return;
      // Only coins the warehouse has loaded; listed-but-empty assets are not shown.
      const rows = all.filter((row) => row.latest_price_usd != null);
      setAssets(rows);
      setSymbol((current) => rows.some((row) => row.symbol === current) ? current
        : rows.find((row) => row.symbol === 'BTC')?.symbol || rows[0]?.symbol || null);
      setError('');
    }).catch((reason) => { if (active) setError(`Unable to load assets: ${reason.message}`); })
      .finally(() => { if (active) setOverviewLoading(false); });
    return () => { active = false; };
  }, [revision]);

  useEffect(() => {
    if (!symbol) {
      setLoading(false);
      setBatch(null);
      return undefined;
    }
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
      <div className="brand"><img className="brand-symbol" src="/logo.svg" alt="" aria-hidden="true" /><strong>CoinSight</strong><span>RESEARCH TERMINAL</span></div>
      <nav className="workspace-switch" aria-label="Workspace">
        <button aria-pressed={workspace === 'market'} onClick={() => setWorkspace('market')}>Market</button>
        <button aria-pressed={workspace === 'operations'} onClick={() => setWorkspace('operations')}>Data</button>
        {paperAccess && <button aria-pressed={workspace === 'paper'} onClick={() => setWorkspace('paper')}>Paper Trade</button>}
        {owner && <button aria-pressed={workspace === 'admin'} onClick={() => setWorkspace('admin')}>Admin</button>}
      </nav>
      <div className="topbar-right">
        <ThemeToggle />
        <a href="/docs/">Docs</a>
        <span className={`connection ${live.connection === 'connected' ? 'online' : 'offline'}`}>
          <i /> {live.connection === 'connected' ? 'Stream connected' : 'Stream reconnecting'}
        </span>
        {workspace === 'operations' && <a href="/api/docs" target="_blank" rel="noopener noreferrer">API</a>}
        <button className="icon-button" type="button" onClick={() => setRevision((value) => value + 1)} disabled={overviewLoading || loading}
          aria-label="Reload data" title="Reload data from the API (does not start an ingestion job)">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2v3.5H10" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
        </button>
        <AccountMenu me={me} />
      </div>
    </header>
    {error && <div className="error-banner" role="alert">{error}</div>}
    {workspace === 'admin' && <Suspense fallback={<p className="admin-empty">Loading…</p>}><AdminConsole /></Suspense>}
    {workspace === 'paper' && <Suspense fallback={<p className="admin-empty">Loading paper portfolio…</p>}><TradingDashboard /></Suspense>}
    <div className={`workspace${workspace === 'operations' ? ' operations-workspace' : ''}`} hidden={workspace === 'admin' || workspace === 'paper'}>
      <AssetRail assets={assets} symbol={symbol} onSelect={setSymbol} warehouse={batch?.warehouse} />
      <main className="analysis" hidden={workspace !== 'market'}>
        <div className="analysis-heading"><div><h1>{symbol && <CoinLogo symbol={symbol} size={36}/>}{symbol ? coinName(symbol, asset?.name) : 'Select a market'} <span className="asset-symbol">{symbol || '—'}</span></h1></div>
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
