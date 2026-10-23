import { useEffect, useState } from 'react';
import { api, amount, utc } from './format.js';
import AgentResponse from './AgentResponse.jsx';
import TraceView from './TraceView.jsx';
import { shortModel } from './AgentTrace.jsx';

// Owners only: the API answers /v1/admin/* with 403 for everyone else (app/admin.py).
const TABS = [['overview', 'Overview'], ['runs', 'Conversations'], ['users', 'Users'], ['models', 'Models'], ['system', 'System']];
const ms = (v) => v == null ? '—' : v < 1000 ? `${Math.round(v)} ms` : `${(v / 1000).toFixed(1)} s`;
const pct = (n, d) => d ? `${(100 * n / d).toFixed(1)}%` : '—';
const who = (row) => row.user_label || (row.user_key?.length > 12 ? `${row.user_key.slice(0, 10)}…` : row.user_key);
// '22 Oct 09:03': the window is at most 90 days, so the year adds nothing.
const when = (v) => v ? new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(v)) : '—';
const ratingText = (r) => r === 1 ? 'up' : r === -1 ? 'down' : '';

function useAdmin(path, deps) {
  const [state, setState] = useState({ data: null, error: '' });
  useEffect(() => {
    let active = true;
    setState((s) => ({ ...s, error: '' }));
    api(path).then((data) => active && setState({ data, error: '' }))
      .catch((e) => active && setState({ data: null, error: e.message }));
    return () => { active = false; };
  }, deps);
  return state;
}

function Metric({ label, value, detail }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</div>;
}

function Table({ columns, rows, onRow, empty = 'Nothing in this window.' }) {
  if (!rows?.length) return <p className="admin-empty">{empty}</p>;
  return <div className="admin-table-wrap"><table className="admin-table">
    <thead><tr>{columns.map(([key, label]) => <th key={key}>{label}</th>)}</tr></thead>
    <tbody>{rows.map((row, i) => <tr key={row.run_id || row.user_key || i} onClick={onRow ? () => onRow(row) : undefined}
      className={onRow ? 'clickable' : undefined}>
      {columns.map(([key, , render]) => <td key={key}>{render ? render(row) : row[key] ?? '—'}</td>)}
    </tr>)}</tbody>
  </table></div>;
}

function DailyBars({ daily }) {
  if (!daily?.length) return null;
  const max = Math.max(...daily.map((d) => d.runs), 1);
  const width = 640, height = 120, bar = width / daily.length;
  return <svg className="admin-bars" viewBox={`0 0 ${width} ${height + 18}`} role="img" aria-label="Runs per day">
    {daily.map((d, i) => {
      const h = (d.runs / max) * height, e = (d.errors / max) * height;
      return <g key={d.day}><title>{`${d.day}: ${d.runs} runs, ${d.users} users, ${d.errors} errors`}</title>
        <rect x={i * bar + 2} y={height - h} width={Math.max(bar - 4, 1)} height={h} className="bar-runs" />
        {e > 0 && <rect x={i * bar + 2} y={height - e} width={Math.max(bar - 4, 1)} height={e} className="bar-errors" />}
        {(daily.length <= 14 || i % Math.ceil(daily.length / 10) === 0) &&
          <text x={i * bar + bar / 2} y={height + 14} textAnchor="middle">{String(d.day).slice(5)}</text>}
      </g>;
    })}
  </svg>;
}

function Overview({ days }) {
  const { data, error } = useAdmin(`/v1/admin/overview?days=${days}`, [days]);
  if (error) return <p className="error-banner">{error}</p>;
  if (!data) return <p className="admin-empty">Loading…</p>;
  const t = data.totals, f = data.feedback;
  return <>
    <div className="metrics admin-metrics">
      <Metric label="Users" value={amount(t.users, 0)} detail={`${amount(t.threads, 0)} conversations`} />
      <Metric label="Questions" value={amount(t.questions, 0)} detail={`${amount(t.runs, 0)} commands in total`} />
      <Metric label="Errors" value={pct(t.errors, t.runs)} detail={`${t.errors} of ${t.runs}`} />
      <Metric label="Latency p50 / p95" value={`${ms(t.latency_p50_ms)} / ${ms(t.latency_p95_ms)}`} />
      <Metric label="Tokens" value={amount(t.input_tokens + t.output_tokens, 0)} detail={`${amount(t.input_tokens, 0)} in · ${amount(t.output_tokens, 0)} out`} />
      <Metric label="Paid models" value={`$${amount(data.paid_spend_usd, 2)}`} detail={`Budget $${amount(data.paid_budget_usd_per_day, 2)} per day`} />
      <Metric label="Feedback" value={`${f.up} up · ${f.down} down`} detail={f.up + f.down ? `${pct(f.up, f.up + f.down)} useful` : 'No ratings yet'} />
      <Metric label="Refused by limits" value={amount(data.refusals.reduce((s, r) => s + r.n, 0), 0)} />
    </div>
    <h3>Runs per day <small>errors in red</small></h3>
    <DailyBars daily={data.daily} />
    <div className="admin-columns">
      <div><h3>Tools the agents called</h3>
        <Table columns={[['tool', 'Tool'], ['calls', 'Calls']]} rows={data.tools} /></div>
      <div><h3>Limit refusals</h3>
        <Table columns={[['reason', 'Reason'], ['n', 'Count']]} rows={data.refusals} empty="No refusals." /></div>
    </div>
  </>;
}

function RunDetail({ runId, onClose }) {
  const { data, error } = useAdmin(`/v1/admin/runs/${runId}`, [runId]);
  return <aside className="admin-detail" aria-label="Conversation detail">
    <div className="admin-detail-head"><strong>Run {String(runId).slice(0, 8)}</strong>
      <button type="button" className="button button-secondary" onClick={onClose}>Close</button></div>
    {error && <p className="error-banner">{error}</p>}
    {data && <>
      <dl className="admin-facts">
        <dt>When</dt><dd>{utc(data.created_at, true)}</dd>
        <dt>User</dt><dd>{who(data)}</dd>
        <dt>Command</dt><dd>{data.command} · {data.symbol}</dd>
        <dt>Model</dt><dd>{data.models?.map(shortModel).join(', ') || '—'}{data.model_requested ? ` (picked ${data.model_requested})` : ''}</dd>
        <dt>Latency</dt><dd>{ms(data.latency_ms)} · {data.llm_calls} LLM call(s) · {amount(data.input_tokens, 0)} in / {amount(data.output_tokens, 0)} out</dd>
        {data.trace_id && <><dt>Trace</dt><dd><code>{data.trace_id}</code><TraceView traceId={data.trace_id}/></dd></>}
        {data.rating != null && <><dt>Feedback</dt><dd>{ratingText(data.rating)}{data.comment ? `: ${data.comment}` : ''}</dd></>}
      </dl>
      <h3>Question</h3><p className="admin-question">{data.question || '—'}</p>
      {data.status === 'error' ? <><h3>Error</h3><pre className="chat-evidence">{data.error}</pre></>
        : <><h3>Answer</h3><div className="chat-markdown"><AgentResponse text={data.answer || ''} meta={data} /></div></>}
    </>}
  </aside>;
}

function Runs({ days, user, setUser }) {
  const [q, setQ] = useState(''), [search, setSearch] = useState('');
  const [status, setStatus] = useState(''), [rating, setRating] = useState('');
  const [rows, setRows] = useState([]), [error, setError] = useState(''), [open, setOpen] = useState(null);
  const [more, setMore] = useState(false);
  const query = (before) => {
    const params = new URLSearchParams({ days, limit: 50 });
    if (search) params.set('q', search);
    if (user) params.set('user', user);
    if (status) params.set('status', status);
    if (rating) params.set('rating', rating);
    if (before) params.set('before', before);
    return `/v1/admin/runs?${params}`;
  };
  useEffect(() => {
    api(query()).then((d) => { setRows(d.runs); setMore(d.runs.length === 50); setError(''); })
      .catch((e) => setError(e.message));
  }, [days, search, user, status, rating]);
  const loadMore = () => api(query(rows.at(-1).created_at)).then((d) => { setRows((r) => [...r, ...d.runs]); setMore(d.runs.length === 50); });

  return <div className={`admin-runs${open ? ' with-detail' : ''}`}>
    <div>
      <form className="admin-filters" onSubmit={(e) => { e.preventDefault(); setSearch(q.trim()); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search questions and answers" aria-label="Search" />
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
          <option value="">Any status</option><option value="ok">OK</option><option value="error">Error</option></select>
        <select value={rating} onChange={(e) => setRating(e.target.value)} aria-label="Feedback">
          <option value="">Any feedback</option><option value="1">Rated up</option><option value="-1">Rated down</option></select>
        {user && <button type="button" className="button button-secondary" onClick={() => setUser(null)}>User {user.slice(0, 10)} ×</button>}
        <button className="button button-secondary" type="submit">Search</button>
      </form>
      {error && <p className="error-banner">{error}</p>}
      <Table onRow={(r) => setOpen(r.run_id)} rows={rows} columns={[
        ['created_at', 'When', (r) => <span className="admin-nowrap">{when(r.created_at)}</span>],
        ['user', 'User', who],
        ['command', 'Agent'],
        ['question', 'Question', (r) => <span className="admin-clip">{r.question || '—'}</span>],
        ['models', 'Model', (r) => r.models?.map(shortModel).join(', ') || '—'],
        ['latency_ms', 'Latency', (r) => ms(r.latency_ms)],
        ['status', 'Status', (r) => <span className={r.status === 'error' ? 'negative' : undefined}>{r.status}</span>],
        ['rating', 'Feedback', (r) => ratingText(r.rating)],
      ].filter(([key]) => !open || !['command', 'models', 'rating'].includes(key))} />
      {more && <button type="button" className="button button-secondary" onClick={loadMore}>Load more</button>}
    </div>
    {open && <RunDetail runId={open} onClose={() => setOpen(null)} />}
  </div>;
}

function Users({ days, onUser }) {
  const { data, error } = useAdmin(`/v1/admin/users?days=${days}`, [days]);
  if (error) return <p className="error-banner">{error}</p>;
  return <>
    <p className="admin-note">Users are shown by a hash of their email; owners are named. Real emails come with Supabase sign-in.</p>
    <Table onRow={(u) => onUser(u.user_key)} rows={data?.users} columns={[
      ['user', 'User', who], ['first_seen', 'First seen', (u) => when(u.first_seen)],
      ['last_seen', 'Last seen', (u) => when(u.last_seen)], ['questions', 'Questions'], ['threads', 'Conversations'],
      ['paid_runs', 'Paid model'], ['errors', 'Errors'], ['refusals', 'Refused'],
      ['feedback', 'Feedback', (u) => `${u.up} up · ${u.down} down`], ['tokens', 'Tokens', (u) => amount(u.tokens, 0)],
    ]} />
  </>;
}

function Models({ days }) {
  const { data, error } = useAdmin(`/v1/admin/models?days=${days}`, [days]);
  if (error) return <p className="error-banner">{error}</p>;
  return <>
    <h3>Model calls</h3>
    <Table rows={data?.calls} columns={[
      ['model', 'Model', (r) => r.label || shortModel(r.model)], ['provider', 'Provider'], ['calls', 'Calls'],
      ['latency', 'Latency p50 / p95', (r) => `${ms(r.latency_p50_ms)} / ${ms(r.latency_p95_ms)}`],
      ['tokens', 'Tokens in / out', (r) => `${amount(r.input_tokens, 0)} / ${amount(r.output_tokens, 0)}`],
      ['after_fallback', 'After a fallback'],
      ['eval', 'Eval pass rate', (r) => r.eval?.pass_rate != null ? `${Math.round(r.eval.pass_rate * 100)}%` : '—'],
    ]} />
    <h3>Failed attempts before a fallback</h3>
    <Table rows={data?.failures} empty="No failed attempts." columns={[
      ['route', 'Route'], ['model', 'Model', (r) => shortModel(r.model)], ['status', 'Error'], ['http_status', 'HTTP'], ['n', 'Count'],
    ]} />
  </>;
}

function System() {
  const { data, error } = useAdmin('/v1/admin/system', []);
  if (error) return <p className="error-banner">{error}</p>;
  const perf = Array.isArray(data?.forecast_performance) ? data.forecast_performance : [];
  return <>
    <h3>Forecast, live performance <small>prediction ledger</small></h3>
    <Table rows={perf} empty="No scored forecasts yet." columns={[
      ['model_id', 'Model'], ['symbol', 'Asset'], ['window_label', 'Window'], ['n', 'Scored hours'],
      ['mae', 'MAE', (r) => amount(r.mae, 5)], ['relative_mae', 'Relative MAE', (r) => amount(r.relative_mae, 3)],
      ['directional_accuracy', 'Direction', (r) => r.directional_accuracy == null ? '—' : `${amount(r.directional_accuracy * 100, 1)}%`],
    ]} />
    <h3>Recent agent errors</h3>
    <Table rows={data?.recent_errors} empty="No errors." columns={[
      ['created_at', 'When', (r) => <span className="admin-nowrap">{when(r.created_at)}</span>], ['command', 'Agent'],
      ['model_requested', 'Picked model'], ['error', 'Error', (r) => <span className="admin-clip">{r.error}</span>],
    ]} />
  </>;
}

export default function AdminConsole() {
  const [tab, setTab] = useState('overview');
  const [days, setDays] = useState(7);
  const [user, setUser] = useState(null);
  return <main className="admin-console">
    <div className="admin-head">
      <div><h1>Admin</h1><p className="admin-note">Usage, conversations and model health. Visible to owners only.</p></div>
      <label>Window <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
        {[1, 7, 30, 90].map((d) => <option key={d} value={d}>{d === 1 ? 'Last 24 h' : `Last ${d} days`}</option>)}
      </select></label>
    </div>
    <nav className="view-tabs" aria-label="Admin views">
      {TABS.map(([key, label]) => <button key={key} aria-pressed={tab === key} onClick={() => setTab(key)}>{label}</button>)}
    </nav>
    {tab === 'overview' && <Overview days={days} />}
    {tab === 'runs' && <Runs days={days} user={user} setUser={setUser} />}
    {tab === 'users' && <Users days={days} onUser={(key) => { setUser(key); setTab('runs'); }} />}
    {tab === 'models' && <Models days={days} />}
    {tab === 'system' && <System />}
  </main>;
}
