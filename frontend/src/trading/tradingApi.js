import { api } from '../format.js';

export function paperApi(path, options = {}) {
  const body = options.body == null || typeof options.body === 'string'
    ? options.body : JSON.stringify(options.body);
  return api(`/v1/paper${path}`, {
    ...options,
    body,
    headers: body == null ? options.headers : { 'Content-Type': 'application/json', ...options.headers },
  });
}

export function agentApi(payload) {
  return api('/v1/agent/command', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function decisionTone(action) {
  if (action === 'BUY') return 'positive';
  if (action === 'SELL' || action === 'NO_TRADE') return 'negative';
  return '';
}

export function equityDomain(...series) {
  const values = series.flatMap((points) => points)
    .map((value) => Number(value))
    .filter(Number.isFinite);
  if (!values.length) return null;
  return { low: Math.min(...values), high: Math.max(...values) };
}

export function equityPath(points, width = 760, height = 220, padding = 18, domain = null) {
  const values = points.map((row) => Number(row.equity_usdt)).filter(Number.isFinite);
  if (values.length < 2) return '';
  const low = Number.isFinite(domain?.low) ? domain.low : Math.min(...values);
  const high = Number.isFinite(domain?.high) ? domain.high : Math.max(...values);
  const range = Math.max(high - low, Math.abs(high) * 0.001, 1);
  return values.map((value, index) => {
    const x = padding + index * (width - 2 * padding) / (values.length - 1);
    const y = height - padding - (value - low) * (height - 2 * padding) / range;
    return `${index ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
}
