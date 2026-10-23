import { accessToken } from './auth.js';

export function amount(value, digits = 2) {
  const number = Number(value);
  return value == null || !Number.isFinite(number) ? '—' :
    new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(number);
}

export function price(value) {
  return value == null ? '—' : `${amount(value)} USDT`;
}

export function percent(value) {
  const number = Number(value);
  return value == null || !Number.isFinite(number) ? '—' :
    `${number >= 0 ? '+' : ''}${number.toFixed(2)}%`;
}

export function utc(value, withTime = false) {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  const options = { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' };
  if (withTime) Object.assign(options, { hour: '2-digit', minute: '2-digit', hour12: false });
  return `${new Intl.DateTimeFormat('en-GB', options).format(parsed)}${withTime ? ' UTC' : ''}`;
}

// "2026-10-23T10:00:00+00:00" -> "10:00 UTC today" / "10:00 UTC yesterday" / "21 Oct, 10:00 UTC"
export function when(value, now = Date.now()) {
  const parsed = new Date(value);
  if (!value || Number.isNaN(parsed.getTime())) return value ? String(value) : '—';
  const time = parsed.toISOString().slice(11, 16) + ' UTC';
  const days = Math.round((Date.parse(new Date(now).toISOString().slice(0, 10)) - Date.parse(parsed.toISOString().slice(0, 10))) / 864e5);
  if (days === 0) return `${time} today`;
  if (days === 1) return `${time} yesterday`;
  const date = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC',
    ...(parsed.getUTCFullYear() !== new Date(now).getUTCFullYear() && { year: 'numeric' }) }).format(parsed);
  return `${date}, ${time}`;
}

// ISO timestamps an answer copied from tool output, shown with when(). Code spans and blocks are left alone.
const ISO = /\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})/g;
export function readableTimes() {
  return tree => {
    const walk = node => {
      if (!Array.isArray(node.children)) return;
      for (const child of node.children) {
        if (child.type === 'text') child.value = child.value.replace(ISO, stamp => when(stamp));
        else if (!['code', 'inlineCode', 'html'].includes(child.type)) walk(child);
      }
    };
    walk(tree);
  };
}

export function age(value, now = Date.now()) {
  if (!value) return 'Freshness unknown';
  const seconds = Math.max(0, Math.floor((now - new Date(value).getTime()) / 1000));
  if (!Number.isFinite(seconds)) return 'Freshness unknown';
  if (seconds < 60) return `${seconds}s old`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m old`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h old`;
  return `${Math.floor(seconds / 86400)}d old`;
}

export async function api(path, options = {}) {
  const token = await accessToken();
  const headers = token ? { ...options.headers, Authorization: `Bearer ${token}` } : options.headers;
  const response = await fetch(`/api${path}`, { ...options, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail=Array.isArray(body?.detail)?body.detail.map(e=>e.msg).join('; '):body?.detail;
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return response.json();
}
