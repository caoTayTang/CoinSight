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

export function age(value, now = Date.now()) {
  if (!value) return 'Freshness unknown';
  const seconds = Math.max(0, Math.floor((now - new Date(value).getTime()) / 1000));
  if (!Number.isFinite(seconds)) return 'Freshness unknown';
  if (seconds < 60) return `${seconds}s old`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m old`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h old`;
  return `${Math.floor(seconds / 86400)}d old`;
}

export async function api(path, options) {
  const response = await fetch(`/api${path}`, options);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `${response.status} ${response.statusText}`);
  }
  return response.json();
}
