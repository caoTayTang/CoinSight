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

// Times show in the viewer's own timezone. A date without a time (a UTC trading day) stays as written.
export function utc(value, withTime = false) {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  const options = { day: '2-digit', month: 'short', year: 'numeric', ...(!withTime && { timeZone: 'UTC' }) };
  if (withTime) Object.assign(options, { hour: '2-digit', minute: '2-digit', hour12: false });
  return new Intl.DateTimeFormat('en-GB', options).format(parsed);
}

const localDay = d => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();

// "2026-10-23T10:00:00+00:00" -> "17:00 today" / "17:00 yesterday" / "21 Oct, 17:00" in the viewer's timezone
export function when(value, now = Date.now()) {
  const parsed = new Date(value);
  if (!value || Number.isNaN(parsed.getTime())) return value ? String(value) : '—';
  const today = new Date(now);
  const time = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false }).format(parsed);
  const days = Math.round((localDay(today) - localDay(parsed)) / 864e5);
  if (days === 0) return `${time} today`;
  if (days === 1) return `${time} yesterday`;
  const date = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short',
    ...(parsed.getFullYear() !== today.getFullYear() && { year: 'numeric' }) }).format(parsed);
  return `${date}, ${time}`;
}

// Times an answer wrote, shown with when(): ISO stamps, "2026-10-22 08:46 UTC", or a bare "08:46 UTC" (placed on
// the day that puts it nearest the time the answer was made). Code spans and blocks are left alone.
const STAMP = /\b(\d{4})[-\u2011](\d{2})[-\u2011](\d{2})[T ](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?\s?(Z|[+-]\d{2}:?\d{2}|UTC)?|\b(\d{1,2}):(\d{2})\s?UTC\b/g;
export function localTimes(text, reference = Date.now()) {
  return text.replace(STAMP, (match, y, mo, d, h, mi, zone, bareH, bareM) => {
    if (y) {
      if (!zone) return match;  // no zone written: can't tell which timezone it means
      const iso = `${y}-${mo}-${d}T${h}:${mi}:00${zone === 'UTC' || zone === 'Z' ? 'Z' : zone.replace(/^([+-]\d{2})(\d{2})$/, '$1:$2')}`;
      return when(iso, Date.now());
    }
    if (+bareH > 23 || +bareM > 59) return match;
    const base = new Date(reference);
    const candidates = [-1, 0, 1].map(shift => Date.UTC(base.getUTCFullYear(), base.getUTCMonth(), base.getUTCDate() + shift, +bareH, +bareM));
    const nearest = candidates.reduce((a, b) => Math.abs(b - reference) < Math.abs(a - reference) ? b : a);
    return when(nearest, Date.now());
  });
}
export function readableTimes(reference) {
  return () => tree => {
    const walk = node => {
      if (!Array.isArray(node.children)) return;
      for (const child of node.children) {
        if (child.type === 'text') child.value = localTimes(child.value, reference);
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
