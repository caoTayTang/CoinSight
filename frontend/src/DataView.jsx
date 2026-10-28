import { useEffect, useState } from 'react';
import { api, when } from './format.js';
import { CoinLogo } from './coins.jsx';
import { dataHealth, dayLabel } from './dataHealth.js';
import { WarehouseProof } from './WarehouseProof.jsx';

const monthLabel = (ms) => new Intl.DateTimeFormat('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' }).format(ms);

function Row({ tone, label, children }) {
  return <li className={`data-row ${tone}`}><i aria-hidden="true" /><b>{label}</b><span>{children}</span></li>;
}

// Operations, for people: a verdict first, one line per pipeline, then which coins have history. The audit tables
// stay one click away under Details.
export function DataView({ batch, live, liveDetails, batchKey }) {
  const [proof, setProof] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    api('/v1/warehouse/proof').then((value) => { if (active) setProof(value); })
      .catch((reason) => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [batchKey]);
  const now = live.now || Date.now();
  const { verdict, rows, history } = dataHealth({ ...batch, live, coverage: proof?.coverage, now });
  const batchId = batch?.warehouse?.data?.latest_batch_id;
  return <section className="data-view">
    <div className={`data-verdict ${verdict.tone}`} role="status"><strong>{verdict.text}</strong><span>Checked {when(now, now)}</span></div>
    <h3 className="evidence-group-title">Pipelines</h3>
    <ul className="data-rows">{rows.map((r) => <Row key={r.key} tone={r.tone} label={r.label}>
      {r.text}{r.detail && <small>{r.detail}</small>}</Row>)}</ul>
    {history && <>
      <h3 className="evidence-group-title">Coins</h3>
      <ul className="data-rows">
        {history.full.symbols.length > 0 && <Row tone="ok" label="Full history">
          <span className="data-coins">{history.full.symbols.map((s) => <span key={s}><CoinLogo symbol={s} size={16} />{s}</span>)}</span>
          <small>Daily candles since {monthLabel(history.full.since)}.</small></Row>}
        {history.recent.symbols.length > 0 && <Row tone="note" label={`${history.recent.symbols.length} recent only`}>
          {history.recent.symbols.join(' · ')}
          <small>Only since {dayLabel(history.recent.since)}; older history is not loaded yet.</small></Row>}
        {history.behind.length > 0 && <Row tone="problem" label="Behind">{history.behind.join(' · ')}
          <small>Newest day older than {dayLabel(history.latest)}.</small></Row>}
        {history.missingHours.length > 0 && <Row tone="note" label="Hourly gaps">
          {history.missingHours.map((m) => `${m.symbol} ${m.count} h`).join(' · ')}
          <small>Hours with no candle since {monthLabel(Math.min(...history.missingHours.map((m) => m.since)))}, out of tens of thousands.</small></Row>}
      </ul>
    </>}
    <details className="operations-detail"><summary>Details: load table, coverage and archive proof</summary>
      <WarehouseProof report={proof} error={error} />
      {batchId && <a className="text-link" href={`/api/v1/lineage/batches/${batchId}`} target="_blank" rel="noopener noreferrer">Batch #{batchId} lineage (JSON) ↗</a>}
    </details>
    <details className="operations-detail"><summary>Live stream details</summary>{liveDetails}</details>
  </section>;
}
