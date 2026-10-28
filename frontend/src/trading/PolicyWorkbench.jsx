import { amount, percent, utc } from '../format.js';
import AgentResponse from '../AgentResponse.jsx';
import { equityDomain, equityPath } from './tradingApi.js';

function nextUtcDate(value) {
  if (!value) return '2026-02-02';
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

function BacktestCurve({ rows = [] }) {
  const policyValues = rows.map((row) => Number(row.equity_usdt));
  const benchmarkValues = rows.map((row) => Number(row.buy_hold_equity_usdt));
  const domain = equityDomain(policyValues, benchmarkValues);
  const path = equityPath(rows, 760, 220, 18, domain);
  if (!path) return null;
  const buyHold = equityPath(
    rows.map((row) => ({ equity_usdt: row.buy_hold_equity_usdt })),
    760, 220, 18, domain,
  );
  return <div className="backtest-curve">
    <div className="backtest-legend" aria-label="Backtest chart legend">
      <span><i className="policy-line" />Policy equity</span>
      <span><i className="benchmark-line" />Buy &amp; hold equity</span>
    </div>
    <svg className="paper-equity-chart backtest-chart" viewBox="0 0 760 220" role="img" aria-label="Policy equity compared with buy and hold equity on one shared USDT scale">
      <path className="benchmark" d={buyHold} /><path d={path} />
    </svg>
    <p className="paper-chart-note">Both lines use the same USDT y-axis scale. Policy equity includes cash and the marked-to-market open position.</p>
  </div>;
}

function ForecastReturnChart({ rows = [] }) {
  const points = rows.filter((row) =>
    Number.isFinite(Number(row.forecast_return_q50))
    && Number.isFinite(Number(row.actual_target_return)));
  if (points.length < 2) return <p className="paper-empty">Run the backtest again to generate forecast-versus-actual return evidence.</p>;
  const width = 980, height = 300, left = 66, right = 24, top = 24, bottom = 66;
  const plotWidth = width - left - right, plotHeight = height - top - bottom;
  const values = points.flatMap((row) => [Number(row.forecast_return_q50), Number(row.actual_target_return)]);
  const maxAbs = Math.max(.001, ...values.map((value) => Math.abs(value))) * 1.08;
  const x = (index) => left + index * plotWidth / (points.length - 1);
  const y = (value) => top + (maxAbs - Number(value)) / (2 * maxAbs) * plotHeight;
  const path = (field) => points.map((row, index) =>
    `${index ? 'L' : 'M'}${x(index).toFixed(1)},${y(row[field]).toFixed(1)}`).join(' ');
  const dateIndexes = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])];
  const markerClass = (action) => `return-action action-${String(action || 'HOLD').toLowerCase()}`;
  const formatReturn = (value) => `${Number(value) >= 0 ? '+' : ''}${(Number(value) * 100).toFixed(2)}%`;
  return <div className="forecast-return-comparison">
    <div className="backtest-legend" aria-label="Forecast return chart legend">
      <span><i className="forecast-return-line" />Predicted q50 return</span>
      <span><i className="actual-return-line" />Actual next-day return</span>
      <span className="action-legend"><b className="action-buy" />BUY <b className="action-sell" />SELL <b className="action-hold" />HOLD</span>
    </div>
    <svg className="forecast-return-chart" viewBox={`0 0 ${width} ${height}`} role="img"
      aria-label="Predicted q50 return compared with actual next-day return and policy actions">
      {[maxAbs, 0, -maxAbs].map((value) => <g key={value}>
        <line className={value === 0 ? 'return-zero' : 'chart-grid'} x1={left} x2={width - right} y1={y(value)} y2={y(value)} />
        <text className="chart-axis" x={left - 9} y={y(value) + 4} textAnchor="end">{formatReturn(value)}</text>
      </g>)}
      <path className="actual-return-path" d={path('actual_target_return')} />
      <path className="forecast-return-path" d={path('forecast_return_q50')} />
      {points.map((row, index) => <circle key={`${row.observed_at}-${row.action}`}
        className={markerClass(row.action)} cx={x(index)} cy={y(row.forecast_return_q50)} r="4.5">
        <title>{`${utc(row.observed_at)} · ${row.action} · predicted ${formatReturn(row.forecast_return_q50)} · actual ${formatReturn(row.actual_target_return)}`}</title>
      </circle>)}
      {dateIndexes.map((index) => <text key={points[index].observed_at} className="chart-axis"
        x={x(index)} y={height - 22}
        textAnchor={index === 0 ? 'start' : index === points.length - 1 ? 'end' : 'middle'}>{utc(points[index].observed_at)}</text>)}
    </svg>
    <p className="paper-chart-note">Above zero means an increase; below zero means a decrease. A marker is directionally correct when predicted q50 and actual return are on the same side of zero. Hover a marker for its date, action and values.</p>
  </div>;
}

export function PolicyEditor({
  policy, fields = [], draft, onChange, onSave, onReset, onBacktest,
  backtestRange, onRangeChange, busy,
}) {
  if (!draft) return <section className="paper-card"><p className="paper-empty">Loading policy…</p></section>;
  return <section className="paper-card policy-workbench">
    <div className="paper-card-head"><div><p className="eyebrow">Paper-only configuration</p><h2>Daily quantile policy</h2>
      <p className="paper-card-copy">Your validated override is isolated from other users. Version and checksum are generated by the server.</p></div>
      <span className="policy-source">{policy?.source === 'user' ? 'Custom policy' : 'Repository default'}</span></div>
    <div className="policy-fields">
      {fields.map((field) => <label className="policy-field" key={field.name}>
        <span>{field.label}</span>
        <input type="number" min={field.min} max={field.max} step={field.step}
          value={draft[field.name] ?? ''}
          onChange={(event) => onChange(field.name, event.target.value)} />
        <small>{field.help}</small>
      </label>)}
      <label className="policy-field policy-notes"><span>Research notes</span>
        <textarea maxLength="1000" value={draft.notes || ''} onChange={(event) => onChange('notes', event.target.value)} />
        <small>Human-readable context only; it does not change policy logic.</small>
      </label>
    </div>
    <dl className="paper-facts policy-identity"><dt>Mode</dt><dd>long_only_spot</dd><dt>Tier</dt><dd>paper-only</dd>
      <dt>Active version</dt><dd>{policy?.config?.version || '—'}</dd><dt>Checksum</dt><dd className="mono">{policy?.config?.sha256?.slice(0, 16) || '—'}…</dd></dl>
    <details className="policy-json-preview"><summary>Preview JSON sent to validation</summary>
      <pre className="paper-json">{JSON.stringify(draft, null, 2)}</pre></details>
    <div className="backtest-range">
      <div><p className="eyebrow">Causal backtest range</p><strong>Select UTC dates</strong>
        <small>Dates before 01 Feb 2026 are locked. End date is exclusive; leave it empty to use the latest fully closed UTC day. Missing warehouse ranges are checked and repaired first.</small></div>
      <label><span>Start date</span><input type="date" min="2026-02-01"
        value={backtestRange.start} onChange={(event) => onRangeChange('start', event.target.value)} /></label>
      <label><span>End date (exclusive)</span><input type="date" min={nextUtcDate(backtestRange.start)}
        value={backtestRange.end} onChange={(event) => onRangeChange('end', event.target.value)} /></label>
    </div>
    <div className="policy-actions"><button className="button button-primary" disabled={busy} onClick={onSave}>Save & activate</button>
      <button className="button button-secondary" disabled={busy} onClick={onBacktest}>Backtest this draft</button>
      <button className="button button-quiet" disabled={busy || policy?.source !== 'user'} onClick={onReset}>Reset default</button></div>
  </section>;
}

export function BacktestPanel({ job, explanation, onExplain, busy }) {
  if (!job) return <section className="paper-card"><div className="paper-card-head"><div><p className="eyebrow">Causal replay</p><h2>Policy backtest</h2></div></div>
    <p className="paper-empty">Edit the policy and choose “Backtest this draft”. The replay uses the model bundle’s frozen test split.</p></section>;
  if (job.status === 'queued' || job.status === 'running') return <section className="paper-card"><h2>Backtest running</h2>
    <progress className="backtest-progress" value={job.progress || 0} max="1" />
    <p>{(job.phase || 'queued').replaceAll('_', ' ')} · {job.completed_steps || 0} / {job.total_steps || '…'} UTC decisions {job.current_cutoff ? `· ${utc(job.current_cutoff, true)}` : ''}</p></section>;
  if (job.status === 'failed') return <section className="paper-card"><h2>Backtest failed</h2><p className="negative">{job.error}</p></section>;
  const result = job.result || {};
  const utility = result.policy_action_utility || {};
  const direction = result.forecast_direction_diagnostics || {};
  const readiness = result.data_readiness || {};
  return <section className="paper-card backtest-report">
    <div className="paper-card-head"><div><p className="eyebrow">Frozen test split</p><h2>Backtest report · {result.symbol}</h2></div>
      <button className="button button-secondary" disabled={busy} onClick={onExplain}>Ask Trade Agent to explain</button></div>
    <div className="paper-metrics compact">
      <div className="paper-metric"><span>Policy return</span><strong className={result.total_return_percent >= 0 ? 'positive' : 'negative'}>{percent(result.total_return_percent)}</strong></div>
      <div className="paper-metric"><span>Profit / loss</span><strong>{amount(result.profit_loss_usdt, 2)} USDT</strong></div>
      <div className="paper-metric"><span>Max drawdown</span><strong className="negative">{percent(Number(result.maximum_drawdown) * 100)}</strong></div>
      <div className="paper-metric"><span>vs buy & hold</span><strong className={result.excess_return_vs_buy_hold_percent >= 0 ? 'positive' : 'negative'}>{percent(result.excess_return_vs_buy_hold_percent)}</strong></div>
      <div className="paper-metric"><span>Trades</span><strong>{result.trade_count ?? '—'}</strong></div>
      <div className="paper-metric"><span>Forecast direction (q50)</span><strong>{direction.directional_accuracy == null ? '—' : percent(Number(direction.directional_accuracy) * 100)}</strong></div>
    </div>
    <div className="backtest-readiness"><strong>Warehouse coverage: {readiness.is_complete ? 'complete' : 'incomplete'}</strong>
      <span>{readiness.backfill_performed ? 'Missing ranges were backfilled before replay.' : 'No backfill was necessary.'}</span>
      <span>{readiness.sync_details?.rows_loaded ? `${readiness.sync_details.rows_loaded} rows loaded` : readiness.backfill_reason || '—'}</span></div>
    <BacktestCurve rows={result.equity_curve} />
    <div className="backtest-subchart-head"><p className="eyebrow">Forecast diagnostics</p><h3>Predicted q50 vs actual next-day return</h3></div>
    <ForecastReturnChart rows={result.equity_curve} />
    <div className="utility-grid">{['BUY', 'SELL', 'HOLD'].map((side) => <div key={side}><strong>{side}</strong>
      <span>{utility[side]?.evaluated_count || 0} evaluated</span>
      <span>{percent(Number(utility[side]?.directionally_useful_rate || 0) * 100)} useful</span></div>)}</div>
    <details><summary>Hold reasons and limitations</summary><pre className="paper-json">{JSON.stringify({ hold_reason_counts: result.hold_reason_counts, limitations: result.limitations }, null, 2)}</pre></details>
    {explanation && <div className="agent-explanation"><p className="eyebrow">Trade Agent interpretation</p><AgentResponse text={explanation} /></div>}
  </section>;
}
