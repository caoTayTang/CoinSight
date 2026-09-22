const state = { overview: [], symbol: null };
const svgNS = "http://www.w3.org/2000/svg";

const el = (id) => document.getElementById(id);
const number = (value) => value == null ? null : Number(value);
const escapeHTML = (value) => String(value ?? "").replace(
  /[&<>"']/g,
  (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character],
);

function money(value) {
  const n = number(value);
  if (n == null || !Number.isFinite(n)) return "--";
  const digits = n >= 1000 ? 2 : n >= 1 ? 3 : 5;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: digits,
  }).format(n);
}

function compact(value) {
  const n = number(value);
  if (n == null || !Number.isFinite(n)) return "--";
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(n);
}

function date(value, includeTime = false) {
  if (!value) return "--";
  const options = includeTime
    ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }
    : { year: "numeric", month: "short", day: "numeric" };
  return new Intl.DateTimeFormat("en-US", options).format(new Date(value));
}

function percent(current, previous) {
  const a = number(current);
  const b = number(previous);
  if (a == null || b == null || b === 0) return null;
  return ((a - b) / b) * 100;
}

async function getJSON(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function setConnection(online) {
  const node = el("connection");
  node.classList.toggle("online", online);
  node.lastChild.textContent = online ? " API connected" : " API offline";
}

function showError(message) {
  const node = el("error");
  node.textContent = message;
  node.hidden = false;
  window.setTimeout(() => { node.hidden = true; }, 5000);
}

function renderAssetControls() {
  el("asset-strip").replaceChildren(...state.overview.map((asset) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `asset-button${asset.symbol === state.symbol ? " active" : ""}`;
    button.textContent = asset.symbol;
    button.addEventListener("click", () => selectAsset(asset.symbol));
    return button;
  }));
}

function renderAssetTable() {
  const rows = state.overview.map((asset) => {
    const move = percent(asset.latest_price_usd, asset.previous_price_usd);
    const row = document.createElement("tr");
    row.classList.toggle("selected", asset.symbol === state.symbol);
    row.innerHTML = `
      <td><div class="asset-cell"><span class="ticker">${escapeHTML(asset.symbol)}</span><span>${escapeHTML(asset.name)}<small class="asset-name">${date(asset.latest_ts)}</small></span></div></td>
      <td>${money(asset.latest_price_usd)}</td>
      <td class="${move == null ? "" : move >= 0 ? "positive" : "negative"}">${move == null ? "--" : `${move >= 0 ? "+" : ""}${move.toFixed(2)}%`}</td>
      <td>${Number(asset.observation_count || 0).toLocaleString()}</td>
      <td>${asset.first_ts ? `${date(asset.first_ts)} - ${date(asset.last_ts)}` : "--"}</td>
      <td>${asset.live_window_end ? date(asset.live_window_end, true) : "--"}</td>`;
    row.addEventListener("click", () => selectAsset(asset.symbol));
    return row;
  });
  el("asset-table").replaceChildren(...rows);
  el("asset-count").textContent = `${state.overview.length} asset${state.overview.length === 1 ? "" : "s"}`;
}

function svgNode(name, attrs = {}) {
  const node = document.createElementNS(svgNS, name);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
  return node;
}

function chart(containerId, rows, valueKey, type) {
  const container = el(containerId);
  if (!rows.length) {
    container.innerHTML = '<div class="empty">No observations available</div>';
    return;
  }

  const width = 900;
  const height = type === "line" ? 280 : 190;
  const margin = { top: 14, right: 16, bottom: 28, left: 70 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const values = rows.map((row) => number(row[valueKey]) || 0);
  let min = type === "bar" ? 0 : Math.min(...values);
  let max = Math.max(...values);
  if (min === max) { min *= 0.99; max *= 1.01; }
  const spread = max - min || 1;
  const x = (index) => margin.left + (rows.length === 1 ? innerWidth / 2 : index * innerWidth / (rows.length - 1));
  const y = (value) => margin.top + (max - value) * innerHeight / spread;
  const svg = svgNode("svg", { viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none" });

  for (let i = 0; i <= 3; i += 1) {
    const lineY = margin.top + i * innerHeight / 3;
    svg.append(svgNode("line", { x1: margin.left, x2: width - margin.right, y1: lineY, y2: lineY, class: "chart-grid" }));
    const label = svgNode("text", { x: margin.left - 10, y: lineY + 4, "text-anchor": "end", class: "chart-label" });
    label.textContent = compact(max - i * spread / 3);
    svg.append(label);
  }

  if (type === "line") {
    const points = values.map((value, index) => `${x(index)},${y(value)}`);
    const area = `${margin.left},${height - margin.bottom} ${points.join(" ")} ${x(rows.length - 1)},${height - margin.bottom}`;
    svg.append(svgNode("polygon", { points: area, class: "price-area" }));
    svg.append(svgNode("polyline", { points: points.join(" "), class: "price-line" }));
    svg.append(svgNode("circle", { cx: x(rows.length - 1), cy: y(values.at(-1)), r: 5, fill: "#13795b" }));
  } else {
    const slot = innerWidth / rows.length;
    const barWidth = Math.max(2, slot * 0.72);
    values.forEach((value, index) => {
      const bar = svgNode("rect", {
        x: margin.left + index * slot + (slot - barWidth) / 2,
        y: y(value), width: barWidth,
        height: Math.max(1, height - margin.bottom - y(value)),
        class: "volume-bar",
      });
      const title = svgNode("title");
      title.textContent = `${date(rows[index].ts)}: ${compact(value)}`;
      bar.append(title);
      svg.append(bar);
    });
  }

  const firstDate = svgNode("text", { x: margin.left, y: height - 7, class: "chart-label" });
  firstDate.textContent = date(rows[0].ts);
  const lastDate = svgNode("text", { x: width - margin.right, y: height - 7, "text-anchor": "end", class: "chart-label" });
  lastDate.textContent = date(rows.at(-1).ts);
  svg.append(firstDate, lastDate);
  container.replaceChildren(svg);
}

function renderSelected(asset, prices, liveMetrics) {
  const rows = [...prices].reverse();
  const values = rows.map((row) => number(row.price_usd)).filter(Number.isFinite);
  const volumes = rows.map((row) => number(row.volume_usd)).filter(Number.isFinite);
  const latest = rows.at(-1);
  const first = rows[0];
  const change = latest && first ? percent(latest.price_usd, first.price_usd) : null;
  const mean = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  const avgVolume = volumes.length ? volumes.reduce((sum, value) => sum + value, 0) / volumes.length : null;

  el("price-title").textContent = `${asset.name} closing price`;
  el("latest-price").textContent = money(latest?.price_usd);
  el("latest-time").textContent = latest ? date(latest.ts, true) : "No observations";
  el("period-return").textContent = change == null ? "--" : `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`;
  el("period-return").className = change == null ? "" : change >= 0 ? "positive" : "negative";
  el("period-range").textContent = first && latest ? `${date(first.ts)} to ${date(latest.ts)}` : "Selected history";
  el("price-range").textContent = values.length ? `${money(Math.min(...values))} - ${money(Math.max(...values))}` : "--";
  el("mean-price").textContent = `Mean ${money(mean)}`;
  el("observations").textContent = rows.length.toLocaleString();
  el("coverage").textContent = first && latest ? `${date(first.ts)} to ${date(latest.ts)}` : "No date range";
  el("average-volume").textContent = `Avg ${compact(avgVolume)}`;

  const live = liveMetrics[0];
  el("live-average").textContent = money(live?.avg_price_usd);
  el("live-volatility").textContent = money(live?.price_volatility);
  el("live-events").textContent = live ? Number(live.event_count).toLocaleString() : "--";
  el("live-window").textContent = live ? date(live.window_end, true) : "--";
  el("live-state").textContent = live ? "Data available" : "No data";
  el("live-state").classList.toggle("online", Boolean(live));

  chart("price-chart", rows, "price_usd", "line");
  chart("volume-chart", rows, "volume_usd", "bar");
}

async function selectAsset(symbol) {
  state.symbol = symbol;
  renderAssetControls();
  renderAssetTable();
  try {
    const [prices, live] = await Promise.all([
      getJSON(`/prices/${encodeURIComponent(symbol)}?limit=240`),
      getJSON(`/live-metrics/${encodeURIComponent(symbol)}?limit=1`),
    ]);
    const asset = state.overview.find((item) => item.symbol === symbol);
    renderSelected(asset, prices, live);
  } catch (error) {
    showError(`Could not load ${symbol}: ${error.message}`);
  }
}

async function refresh() {
  el("refresh").disabled = true;
  try {
    state.overview = await getJSON("/overview");
    setConnection(true);
    el("last-refresh").textContent = new Intl.DateTimeFormat("en-US", {
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).format(new Date());
    const symbol = state.overview.some((item) => item.symbol === state.symbol)
      ? state.symbol
      : state.overview[0]?.symbol;
    renderAssetControls();
    renderAssetTable();
    if (symbol) await selectAsset(symbol);
  } catch (error) {
    setConnection(false);
    showError(`Dashboard refresh failed: ${error.message}`);
  } finally {
    el("refresh").disabled = false;
  }
}

el("refresh").addEventListener("click", refresh);
refresh();
window.setInterval(refresh, 30000);
