import { useEffect, useMemo, useState } from 'react';
import { amount } from '../format.js';

const MIN_HOURS = 24;
const MAX_HOURS = 365 * 24;

function quantilePrices(decision) {
  const forecast = decision?.evidence?.forecast || {};
  const reference = Number(forecast.reference_close_usdt);
  const price = (name, returnName) => {
    const direct = Number(forecast[name]);
    if (Number.isFinite(direct)) return direct;
    const change = Number(forecast[returnName]);
    return Number.isFinite(reference) && Number.isFinite(change)
      ? reference * Math.exp(change) : null;
  };
  return {
    reference,
    q10: price('predicted_close_q10_usdt', 'return_q10'),
    q50: price('predicted_close_q50_usdt', 'return_q50'),
    q90: price('predicted_close_q90_usdt', 'return_q90'),
    target: forecast.target_open || decision?.target_close,
  };
}

function clamp(value, low, high) { return Math.min(high, Math.max(low, value)); }

function tickLabel(value, hourly) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'target';
  return new Intl.DateTimeFormat('en-GB', hourly
    ? { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC', hour12: false }
    : { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' }
  ).format(date);
}

function uniqueTickIndexes(length, count = 5) {
  if (length <= 1) return [0];
  const size = Math.min(count, length);
  return [...new Set(Array.from({ length: size }, (_, index) =>
    Math.round(index * (length - 1) / (size - 1))))];
}

export default function ForecastCandleChart({ dailyCandles = [], hourlyCandles = [], decision }) {
  const [zoomHours, setZoomHours] = useState(60 * 24);
  const [panHours, setPanHours] = useState(0);
  useEffect(() => { setPanHours(0); }, [dailyCandles.at(-1)?.open_time, hourlyCandles.at(-1)?.open_time]);

  const hourly = zoomHours <= 14 * 24;
  const source = hourly ? hourlyCandles : dailyCandles;
  const stepHours = hourly ? 1 : 24;
  const visibleCount = Math.max(2, Math.ceil(zoomHours / stepHours));
  const panRows = Math.round(panHours / stepHours);
  const end = Math.max(1, source.length - panRows);
  const start = Math.max(0, end - visibleCount);
  const visible = source.slice(start, end);
  const atLatest = panRows === 0;
  const forecast = quantilePrices(decision);
  const maxPanHours = Math.max(0, (source.length - Math.min(source.length, visibleCount)) * stepHours);

  const setZoom = (hours) => {
    setZoomHours(clamp(Math.round(hours), MIN_HOURS, MAX_HOURS));
    setPanHours((current) => clamp(current, 0, maxPanHours));
  };
  const zoomBy = (factor) => setZoom(zoomHours * factor);
  const panBy = (direction) => setPanHours((current) =>
    clamp(current + direction * Math.max(stepHours, zoomHours * .45), 0, maxPanHours));
  const onWheel = (event) => {
    event.preventDefault();
    zoomBy(event.deltaY < 0 ? .72 : 1.38);
  };

  const geometry = useMemo(() => {
    if (visible.length < 2) return null;
    const values = visible.flatMap((row) => [row.low_price, row.high_price].map(Number));
    if (atLatest) for (const value of [forecast.q10, forecast.q50, forecast.q90]) {
      if (Number.isFinite(value)) values.push(value);
    }
    const low = Math.min(...values), high = Math.max(...values);
    const range = Math.max(high - low, high * .01, 1);
    const width = 980, height = 360, left = 72, right = 165, top = 22, bottom = 58;
    const chartW = width - left - right, chartH = height - top - bottom;
    const step = chartW / visible.length;
    const y = (value) => top + (high - Number(value)) / range * chartH;
    return { low, high, range, width, height, left, right, top, bottom, chartW, chartH, step, y };
  }, [visible, atLatest, forecast.q10, forecast.q50, forecast.q90]);

  if (!geometry) return <div className="paper-empty">Candles are unavailable for this zoom level.</div>;
  const { high, range, width, height, left, right, top, chartH, step, y } = geometry;
  const lastX = left + (visible.length - .5) * step;
  const targetX = width - right + 68;
  const bodyWidth = clamp(step * .62, 1.2, 12);
  const showForecast = atLatest && Number.isFinite(forecast.q50) && Number.isFinite(forecast.reference);
  const ticks = uniqueTickIndexes(visible.length);

  return <div className="forecast-chart-wrap">
    <div className="chart-toolbar">
      <div className="chart-presets" aria-label="Chart range presets">
        {[['1D', 24], ['7D', 168], ['30D', 720], ['90D', 2160], ['1Y', 8760]].map(([label, hours]) =>
          <button key={label} className={zoomHours === hours ? 'active' : ''} onClick={() => { setZoom(hours); setPanHours(0); }}>{label}</button>)}
      </div>
      <div className="chart-navigation">
        <button onClick={() => panBy(1)} disabled={panHours >= maxPanHours} aria-label="Pan to older candles">←</button>
        <button onClick={() => panBy(-1)} disabled={panHours <= 0} aria-label="Pan to newer candles">→</button>
        <button onClick={() => zoomBy(.72)} aria-label="Zoom in">＋</button>
        <button onClick={() => zoomBy(1.38)} aria-label="Zoom out">−</button>
        <button onClick={() => { setZoom(60 * 24); setPanHours(0); }}>Reset</button>
        <span className="chart-resolution">{hourly ? '1h candles' : '1d candles'} · {visible.length} bars</span>
      </div>
    </div>
    <input className="chart-zoom-slider" aria-label="Chart zoom range" type="range"
      min={MIN_HOURS} max={MAX_HOURS} step="24" value={zoomHours}
      onChange={(event) => setZoom(Number(event.target.value))} />
    <svg className="forecast-candle-chart" viewBox={`0 0 ${width} ${height}`} role="img"
      aria-label={`${hourly ? 'Hourly' : 'Daily'} candles with q10 q50 q90 next-close forecast`}
      onWheel={onWheel}>
      {[0, .25, .5, .75, 1].map((ratio) => {
        const value = high - ratio * range;
        const yy = top + ratio * chartH;
        return <g key={ratio}><line className="chart-grid" x1={left} x2={width - right} y1={yy} y2={yy} />
          <text className="chart-axis" x={left - 10} y={yy + 4} textAnchor="end">{amount(value, 0)}</text></g>;
      })}
      {visible.map((row, index) => {
        const x = left + (index + .5) * step;
        const open = Number(row.open_price), close = Number(row.close_price);
        const up = close >= open;
        return <g key={`${row.open_time}-${index}`} className={up ? 'candle-up' : 'candle-down'}>
          <line x1={x} x2={x} y1={y(row.high_price)} y2={y(row.low_price)} />
          <rect x={x - bodyWidth / 2} y={y(Math.max(open, close))} width={bodyWidth}
            height={Math.max(1.2, Math.abs(y(open) - y(close)))} />
        </g>;
      })}
      {showForecast && <g className="forecast-overlay">
        <line className="forecast-link" x1={lastX} y1={y(forecast.reference)} x2={targetX} y2={y(forecast.q50)} />
        <line className="forecast-interval" x1={targetX} x2={targetX} y1={y(forecast.q90)} y2={y(forecast.q10)} />
        <circle className="forecast-q10" cx={targetX} cy={y(forecast.q10)} r="4" />
        <circle className="forecast-q50" cx={targetX} cy={y(forecast.q50)} r="6" />
        <circle className="forecast-q90" cx={targetX} cy={y(forecast.q90)} r="4" />
        <text className="forecast-label" x={targetX + 11} y={y(forecast.q90) + 4}>q90 {amount(forecast.q90, 0)}</text>
        <text className="forecast-label q50" x={targetX + 11} y={y(forecast.q50) + 4}>q50 {amount(forecast.q50, 0)}</text>
        <text className="forecast-label" x={targetX + 11} y={y(forecast.q10) + 4}>q10 {amount(forecast.q10, 0)}</text>
        <text className="chart-axis target-tick" x={targetX} y={height - 12} textAnchor="middle">{tickLabel(forecast.target, false)}</text>
      </g>}
      {ticks.map((index) => {
        const x = left + (index + .5) * step;
        const anchor = index === 0 ? 'start' : index === visible.length - 1 ? 'end' : 'middle';
        return <text key={visible[index].open_time} className="chart-axis" x={x} y={height - 30}
          textAnchor={anchor}>{tickLabel(visible[index].open_time, hourly)}</text>;
      })}
    </svg>
    <p className="paper-chart-note">Scroll over the chart or use controls to zoom; arrows pan through history. At 14 days or less it automatically switches to hourly candles. The q10–q90 overlay is shown only at the latest edge.</p>
  </div>;
}
