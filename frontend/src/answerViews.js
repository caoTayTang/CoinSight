// Plain-language views of tool evidence: where a request's time went, whether model inputs drifted, and the
// steps the agent took. Pure functions so they can be tested without a browser.

const finite = n => typeof n === 'number' && Number.isFinite(n);

// ---- Request trace: split the total time into what the user waited for. ----

const PROVIDERS = {groq: 'Groq', openrouter: 'OpenRouter', 'aws.bedrock': 'Bedrock', bedrock: 'Bedrock', vllm: 'self-hosted'};
const ERRORS = {HTTP429: 'rate limited', HTTP413: 'request too large', HTTP400: 'rejected', HTTP500: 'server error', HTTP503: 'unavailable'};

export function traceBreakdown(result) {
  const spans = Array.isArray(result?.spans) ? result.spans.filter(s => s && finite(s.duration_ms) && s.duration_ms >= 0) : [];
  if (!spans.length) return null;
  const total = finite(result.duration_ms) ? result.duration_ms : Math.max(...spans.map(s => s.duration_ms));
  const children = new Map();
  for (const s of spans) children.set(s.parent_span_id, [...(children.get(s.parent_span_id) || []), s]);
  const hasModelCall = s => (children.get(s.span_id) || []).some(c => c.operation === 'llm.provider' || hasModelCall(c));
  const models = spans.filter(s => s.operation === 'llm.provider');
  const answered = models.filter(s => !s.error), failed = models.filter(s => s.error);
  // A tool that delegates to another agent contains model calls; count only its own work.
  const tools = spans.filter(s => /^tool\./.test(s.operation) && !hasModelCall(s));
  const sum = list => list.reduce((n, s) => n + s.duration_ms, 0);
  const parts = [
    {key: 'model', label: 'Model writing', ms: sum(answered)},
    {key: 'failed', label: 'Failed model attempts', ms: sum(failed)},
    {key: 'tools', label: 'Tools and data', ms: sum(tools)},
  ];
  parts.push({key: 'other', label: 'Network and agent hand-offs', ms: Math.max(0, total - parts.reduce((n, p) => n + p.ms, 0))});
  const attempts = new Map();
  for (const s of failed) {
    const a = s.attributes || {};
    const label = `${PROVIDERS[a['gen_ai.provider.name']] || a['gen_ai.provider.name'] || 'model'} ${ERRORS[a['error.type']] || a['error.type'] || 'error'}`;
    attempts.set(label, (attempts.get(label) || 0) + 1);
  }
  const slowestTool = tools.slice().sort((a, b) => b.duration_ms - a.duration_ms)[0];
  return {
    total, parts: parts.filter(p => p.ms > 0),
    modelCalls: answered.length, failedAttempts: [...attempts].map(([label, count]) => ({label, count})),
    slowestTool: slowestTool && {name: slowestTool.operation.slice(5).replace(/_/g, ' '), ms: slowestTool.duration_ms},
  };
}

// ---- Drift: one verdict, then the inputs that moved most, in plain words. ----

export const FEATURE_NAMES = {
  momentum6_z: '6-hour price trend', volatility_ratio6: 'Recent volatility vs usual', range_ratio: 'Hourly high-low range',
  trades_z: 'Number of trades', volume_z: 'Trading volume', lower_wick_fraction: 'Dips bought back within the hour',
  upper_wick_fraction: 'Spikes sold off within the hour', return_z: 'Hourly price move', body_z: 'Candle body size',
  close_position: 'Where the hour closed in its range',
};
export const DRIFT_WATCH = 0.25;  // PSI watch level
const level = psi => psi >= DRIFT_WATCH ? 'changed' : psi >= 0.1 ? 'shifting' : 'stable';

export function driftSummary(rows) {
  const valid = (Array.isArray(rows) ? rows : []).filter(r => r && typeof r.feature === 'string' && finite(r.psi) && r.psi >= 0)
    .sort((a, b) => b.psi - a.psi);
  if (!valid.length) return null;
  const changed = valid.filter(r => r.psi >= DRIFT_WATCH).length, shifting = valid.filter(r => level(r.psi) === 'shifting').length;
  const verdict = changed ? 'changed' : shifting ? 'shifting' : 'stable';
  const headline = {
    stable: 'Recent market inputs look like the data the model was trained on.',
    shifting: `Recent market inputs are starting to differ from the training data (${shifting} of ${valid.length} inputs), but none has crossed the watch level.`,
    changed: `${changed} of ${valid.length} market inputs now look different from the training data. Forecasts may be less reliable.`,
  }[verdict];
  return {
    verdict, headline,
    top: valid.slice(0, 3).map(r => ({feature: r.feature, label: FEATURE_NAMES[r.feature] || r.feature.replace(/_/g, ' '),
      psi: r.psi, level: level(r.psi), share: Math.min(1, r.psi / DRIFT_WATCH)})),
    all: valid,
  };
}

// ---- Steps: what the agent did, as short verbs, in order. ----

const VERBS = {
  predict_hourly: 'Checked the forecast', model_health: 'Checked model accuracy', detect_market_anomaly: 'Checked for unusual moves',
  market_data: 'Read market prices', warehouse_coverage: 'Counted hourly candles', warehouse_status: 'Checked recent batches',
  warehouse_reconciliation: 'Checked load accounting', warehouse_quality: 'Read quality checks', warehouse_mart_parity: 'Compared fact and mart totals',
  warehouse_lineage: 'Traced data lineage', service_health: 'Checked services', airflow_status: 'Checked Airflow runs',
  search_traces: 'Searched traces', inspect_trace: 'Inspected a trace', investigate_warehouse: 'Asked the Operations agent',
  save_memory: 'Saved a note for next time',
};
const skillTitle = name => String(name || '').replace(/-/g, ' ');

export function stepSummary(meta) {
  const steps = Array.isArray(meta?.steps) ? meta.steps : [];
  const items = [];
  for (const step of steps) {
    for (const tool of step.tools || []) {
      const label = tool.name === 'load_skill' ? `Read the ${skillTitle(tool.arguments?.name)} guide` : VERBS[tool.name] || tool.name.replace(/_/g, ' ');
      if (items.at(-1)?.label === label) { items.at(-1).count += 1; continue; }
      items.push({label, failed: tool.status === 'error', count: 1});
    }
    if (step.kind === 'budget_exhausted') items.push({label: 'Stopped: step budget used up', failed: true, count: 1});
  }
  if (!items.length) return null;
  const ms = steps.reduce((n, s) => n + (s.latency_ms || 0) + (s.tools || []).reduce((m, t) => m + (t.latency_ms || 0), 0), 0);
  return {items, seconds: ms ? ms / 1000 : null};
}
