// The Data tab in plain words: one verdict, a line per pipeline, and which coins have full history.
// Pure functions so they can be tested without a browser.

import { when } from './format.js';

const DAY = 864e5;
// The daily load runs at 06:00 UTC (pipeline/settings.yaml) and loads the previous UTC day. Before 07:00 UTC the
// newest loaded day may still be the day before yesterday.
const LOAD_DONE_UTC_HOUR = 7;
// A coin loaded for less than this has "recent history only".
const FULL_HISTORY_DAYS = 365;

const dayStart = (ms) => Math.floor(ms / DAY) * DAY;
const dayOf = (iso) => { const t = Date.parse(iso); return Number.isNaN(t) ? null : dayStart(t); };
export const dayLabel = (ms) => new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(ms);

export function expectedLatestDay(now) {
  const lag = new Date(now).getUTCHours() >= LOAD_DONE_UTC_HOUR ? 1 : 2;
  return dayStart(now) - lag * DAY;
}

// Coverage rows from /v1/warehouse/proof, grouped per coin.
export function coinHistory(coverage, now = Date.now()) {
  const rows = Array.isArray(coverage) ? coverage : [];
  const daily = rows.filter((r) => r?.candle_interval === '1d' && dayOf(r.first_open) != null && dayOf(r.last_open) != null);
  if (!daily.length) return null;
  const latest = Math.max(...daily.map((r) => dayOf(r.last_open)));
  const full = [], recent = [];
  for (const r of daily.sort((a, b) => a.symbol.localeCompare(b.symbol))) {
    (latest - dayOf(r.first_open) >= FULL_HISTORY_DAYS * DAY ? full : recent).push(r);
  }
  const since = (list) => list.length ? Math.min(...list.map((r) => dayOf(r.first_open))) : null;
  const missingHours = rows.filter((r) => r?.candle_interval === '1h' && r.missing_candles > 0)
    .map((r) => ({ symbol: r.symbol, count: r.missing_candles, since: dayOf(r.first_open) }));
  return {
    latest, behind: daily.filter((r) => dayOf(r.last_open) < latest).map((r) => r.symbol),
    full: { symbols: full.map((r) => r.symbol), since: since(full) },
    recent: { symbols: recent.map((r) => r.symbol), since: since(recent) },
    missingHours, late: latest < expectedLatestDay(now),
  };
}

// tone: ok | note | problem
export function dataHealth({ warehouse, evaluation, prediction, live, coverage, now = Date.now() }) {
  const rows = [];
  const history = coinHistory(coverage, now);

  const w = warehouse?.data;
  if (!w?.latest_batch_id) rows.push({ key: 'load', label: 'Daily load', tone: 'problem', text: 'No load has run yet.' });
  else {
    const failed = w.latest_batch_status !== 'success';
    const late = history?.late;
    rows.push({
      key: 'load', label: 'Daily load', tone: failed || late ? 'problem' : w.rejected_rows ? 'note' : 'ok',
      text: failed ? `Last load ${w.latest_batch_status} (${when(w.latest_batch_finished_at, now)}).`
        : late ? `Behind: newest day is ${dayLabel(history.latest)}, expected ${dayLabel(expectedLatestDay(now))}.`
          : `Ran ${when(w.latest_batch_finished_at, now)}${history ? `; newest day ${dayLabel(history.latest)}` : ''}.`,
      detail: w.rejected_rows ? `${w.rejected_rows} rows failed quality checks and were left out.` : null,
    });
  }

  const e = evaluation?.data;
  const checked = evaluation?.provenance?.computed_at;
  const published = prediction?.status === 'ready' && prediction?.data;
  rows.push(!e ? { key: 'model', label: 'Up/down model', tone: 'note', text: 'Not evaluated yet.' } : {
    key: 'model', label: 'Up/down model', tone: e.decision === 'accepted' && published ? 'ok' : 'note',
    text: e.decision === 'accepted'
      ? (published ? `Published tomorrow's up/down probability (model checked ${when(checked, now)}).` : 'Model accepted, but no probability is published yet.')
      : `No model in use: the last one tested was no better than guessing${checked ? ` (${when(checked, now)})` : ''}. Retested every Monday.`,
  });

  const s = live?.summary;
  const seen = s?.data?.observed_minutes, expected = s?.data?.expected_minutes;
  // Right after the page opens the stream is still connecting; that is not a fault yet.
  const connecting = seen == null && live?.connection && live.connection !== 'connected';
  rows.push(connecting ? { key: 'live', label: 'Live prices', tone: 'note', text: 'Connecting to the live feed…' }
    : seen == null ? { key: 'live', label: 'Live prices', tone: 'problem', text: s?.quality?.warnings?.[0] || 'No live candles received.' } : {
    key: 'live', label: 'Live prices', tone: seen >= expected - 1 ? 'ok' : seen > 0 ? 'note' : 'problem',
    text: `${seen} of ${expected} one-minute candles in the last 15 minutes.`,
  });

  const problems = rows.filter((r) => r.tone === 'problem');
  const verdict = problems.length
    ? { tone: 'problem', text: `Needs attention: ${problems.map((r) => r.label.toLowerCase()).join(', ')}.` }
    : { tone: 'ok', text: `Data is current${history ? `. Newest day: ${dayLabel(history.latest)}` : ''}.` };
  return { verdict, rows, history };
}
