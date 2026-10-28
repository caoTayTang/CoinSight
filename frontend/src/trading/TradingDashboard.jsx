import { useCallback, useEffect, useMemo, useState } from 'react';
import { amount, percent, utc } from '../format.js';
import { agentApi, decisionTone, equityPath, paperApi } from './tradingApi.js';
import ForecastCandleChart from './ForecastCandleChart.jsx';
import { BacktestPanel, PolicyEditor } from './PolicyWorkbench.jsx';
import TradeAnalytics from './TradeAnalytics.jsx';

const EMPTY = { positions: [], equity_usdt: 0, cash_usdt: 0, total_return: 0, drawdown: 0 };

function money(value) {
  return value == null ? '—' : `${amount(value, 2)} USDT`;
}

function Metric({ label, value, tone = '', detail }) {
  return <div className="paper-metric"><span>{label}</span><strong className={tone}>{value}</strong>
    {detail && <small>{detail}</small>}</div>;
}

function EquityChart({ rows }) {
  const path = equityPath(rows);
  if (!path) return <div className="paper-empty">Equity history appears after the first confirmed fill.</div>;
  return <svg className="paper-equity-chart" viewBox="0 0 760 220" role="img" aria-label="Paper portfolio equity curve">
    <path d={path} />
  </svg>;
}

function DecisionPanel({ decision, symbol, onCreate, onPreview, busy }) {
  const evidence = decision?.evidence || {};
  const forecast = evidence.forecast || {};
  const signed = Number(decision?.signed_score);
  const bias = !Number.isFinite(signed) || signed === 0 ? 'Neutral / blocked' : signed > 0 ? 'Bullish' : 'Bearish';
  const priceAge = Number(decision?.execution_price_age_seconds);
  const stale = (decision?.reasons || []).includes('execution_price_stale');
  return <section className="paper-card paper-decision">
    <div className="paper-card-head"><div><p className="eyebrow">Frozen evidence</p><h2>Policy decision · {symbol}</h2></div>
      <button className="button button-primary" disabled={busy} onClick={onCreate}>Evaluate now</button></div>
    {!decision ? <p className="paper-empty">No decision yet. Evaluation loads current forecast support, then stores the evidence and policy version.</p> : <>
      <div className="paper-action-row">
        <strong className={decisionTone(decision.action)}>{decision.action}</strong>
        <span>support {amount(Number(decision.support_score) * 100, 1)} / 100</span>
        <span>signed {Number.isFinite(signed) ? `${signed >= 0 ? '+' : ''}${amount(signed * 100, 1)} / 100` : '—'}</span>
        <span>bias {bias}</span>
        <span>target allocation {percent(Number(decision.target_position_fraction) * 100)}</span>
      </div>
      <div className="paper-quantiles">
        <Metric label="q10 return" value={percent(Number(forecast.return_q10) * 100)} />
        <Metric label="q50 return" value={percent(Number(forecast.return_q50) * 100)} />
        <Metric label="q90 return" value={percent(Number(forecast.return_q90) * 100)} />
      </div>
      <dl className="paper-facts">
        <dt>Target close</dt><dd>{utc(decision.target_close, true)}</dd>
        <dt>Policy</dt><dd>{decision.policy_id} · {decision.policy_version}</dd>
        <dt>Model</dt><dd>{decision.model_id} · {decision.model_version}</dd>
        <dt>Current allocation</dt><dd>{decision.current_position_fraction == null ? '—' : percent(Number(decision.current_position_fraction) * 100)}</dd>
        <dt>Execution price</dt><dd>{money(decision.execution_price_usdt)}</dd>
        <dt>Price observed</dt><dd>{utc(decision.execution_price_observed_at, true)}</dd>
        <dt>Evaluated</dt><dd>{utc(decision.evaluated_at || decision.created_at, true)}</dd>
        <dt>Price age at evaluation</dt><dd>{Number.isFinite(priceAge) ? `${amount(priceAge, 1)} seconds` : '—'}</dd>
        <dt>Reasons</dt><dd>{(decision.reasons || []).join(', ') || '—'}</dd>
        <dt>Risk flags</dt><dd>{(decision.risk_flags || []).join(', ') || 'none'}</dd>
      </dl>
      {stale && <p className="decision-warning">Order creation was blocked because the latest closed one-minute price was older than the policy limit at the displayed evaluation time. Refreshing market data does not mutate this frozen decision; click Evaluate now again.</p>}
      <button className="button button-secondary" disabled={busy || !decision.executable} onClick={onPreview}>
        {decision.executable ? 'Preview paper order' : 'No executable order'}
      </button>
    </>}
  </section>;
}

function ConfirmOrder({ preview, busy, onCancel, onConfirm }) {
  if (!preview) return null;
  return <div className="paper-confirm" role="dialog" aria-modal="true" aria-labelledby="paper-confirm-title">
    <div><h2 id="paper-confirm-title">Confirm simulated {preview.side}</h2>
      <p>This writes a paper fill only. It cannot contact an exchange. No fee is simulated; {amount(preview.slippage_bps, 1)} bps slippage is applied.</p>
      <dl className="paper-facts">
        <dt>Quantity</dt><dd>{amount(preview.quantity, 8)} {preview.symbol}</dd>
        <dt>Market price</dt><dd>{money(preview.market_price_usdt)}</dd>
        <dt>Simulated fill</dt><dd>{money(preview.fill_price_usdt)}</dd>
        <dt>Notional</dt><dd>{money(preview.notional_usdt)}</dd>
        <dt>Price candle</dt><dd>{utc(preview.source_candle_time, true)}</dd>
      </dl>
      <div className="paper-confirm-actions"><button className="button button-secondary" onClick={onCancel}>Cancel</button>
        <button className="button button-primary" disabled={busy} onClick={onConfirm}>Confirm paper fill</button></div>
    </div>
  </div>;
}

export default function TradingDashboard() {
  const [portfolios, setPortfolios] = useState([]);
  const [portfolioId, setPortfolioId] = useState('');
  const [portfolio, setPortfolio] = useState(EMPTY);
  const [symbol, setSymbol] = useState('BTC');
  const [decision, setDecision] = useState(null);
  const [preview, setPreview] = useState(null);
  const [orders, setOrders] = useState([]);
  const [equity, setEquity] = useState([]);
  const [candles, setCandles] = useState({ daily: [], hourly: [] });
  const [analytics, setAnalytics] = useState(null);
  const [policy, setPolicy] = useState(null);
  const [policyDraft, setPolicyDraft] = useState(null);
  const [backtest, setBacktest] = useState(null);
  const [backtestRange, setBacktestRange] = useState({ start: '2026-02-01', end: '' });
  const [explanation, setExplanation] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const loadPortfolios = useCallback(async () => {
    const rows = (await paperApi('/portfolios')).portfolios || [];
    setPortfolios(rows);
    setPortfolioId((current) => current || rows[0]?.portfolio_id || '');
  }, []);

  const loadPolicy = useCallback(async () => {
    const result = await paperApi('/policy');
    setPolicy(result); setPolicyDraft({ ...result.config });
  }, []);

  const refresh = useCallback(async () => {
    if (!portfolioId) return;
    const [summary, latest, history, curve, dailyMarket, hourlyMarket, outcomes] = await Promise.all([
      paperApi(`/portfolios/${portfolioId}`),
      paperApi(`/portfolios/${portfolioId}/decisions/latest?symbol=${symbol}`),
      paperApi(`/portfolios/${portfolioId}/orders?limit=100`),
      paperApi(`/portfolios/${portfolioId}/equity?limit=1000`),
      paperApi(`/market/${symbol}/candles?interval=1d&limit=730`),
      paperApi(`/market/${symbol}/candles?interval=1h&limit=4000`),
      paperApi(`/portfolios/${portfolioId}/analytics?limit=500`),
    ]);
    setPortfolio(summary);
    setDecision(latest.decision || null);
    setOrders(history.orders || []);
    setEquity(curve.equity || []);
    setCandles({ daily: dailyMarket.candles || [], hourly: hourlyMarket.candles || [] });
    setAnalytics(outcomes);
  }, [portfolioId, symbol]);

  useEffect(() => { loadPortfolios().catch((reason) => setError(reason.message)); }, [loadPortfolios]);
  useEffect(() => { loadPolicy().catch((reason) => setError(reason.message)); }, [loadPolicy]);
  useEffect(() => { refresh().catch((reason) => setError(reason.message)); }, [refresh]);
  useEffect(() => {
    if (!backtest?.job_id || !['queued', 'running'].includes(backtest.status)) return undefined;
    const timer = window.setInterval(async () => {
      try { setBacktest(await paperApi(`/backtests/${backtest.job_id}`)); }
      catch (reason) { setError(reason.message); window.clearInterval(timer); }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [backtest?.job_id, backtest?.status]);

  const perform = async (task) => {
    setBusy(true); setError(''); setNotice('');
    try { await task(); } catch (reason) { setError(reason.message); } finally { setBusy(false); }
  };
  const createPortfolio = () => perform(async () => {
    const created = await paperApi('/portfolios', { method: 'POST', body: { name: `Paper ${new Date().toISOString().slice(0, 10)}`, initial_cash_usdt: 100000 } });
    await loadPortfolios(); setPortfolioId(created.portfolio_id); setNotice('Paper portfolio created.');
  });
  const createDecision = () => perform(async () => {
    const created = await paperApi(`/portfolios/${portfolioId}/decisions`, { method: 'POST', body: { symbol } });
    setDecision(created); setPreview(null); setNotice('Decision stored with frozen evidence.'); await refresh();
  });
  const previewOrder = () => perform(async () => {
    setPreview(await paperApi(`/portfolios/${portfolioId}/orders/preview`, { method: 'POST', body: { decision_id: decision.decision_id } }));
  });
  const confirmOrder = () => perform(async () => {
    await paperApi(`/portfolios/${portfolioId}/orders`, { method: 'POST', body: {
      decision_id: decision.decision_id, idempotency_key: crypto.randomUUID(),
      expected_source_candle_time: preview.source_candle_time,
    } });
    setPreview(null); setNotice('Paper fill recorded.'); await refresh();
  });
  const changePolicy = (name, value) => setPolicyDraft((current) => ({
    ...current, [name]: name === 'notes' ? value : Number(value),
  }));
  const changeBacktestRange = (name, value) => setBacktestRange((current) => {
    const next = { ...current, [name]: value };
    if (name === 'start' && next.end && next.end <= value) next.end = '';
    return next;
  });
  const savePolicy = () => perform(async () => {
    const result = await paperApi('/policy', { method: 'PUT', body: { config: policyDraft } });
    setPolicy(result); setPolicyDraft({ ...result.config });
    setNotice('Policy validated and activated for your account.');
  });
  const resetPolicy = () => perform(async () => {
    const result = await paperApi('/policy', { method: 'DELETE' });
    setPolicy(result); setPolicyDraft({ ...result.config });
    setNotice('Policy reset to the repository default.');
  });
  const runBacktest = () => perform(async () => {
    setExplanation('');
    const result = await paperApi('/backtests', {
      method: 'POST', body: {
        symbol, policy_config: policyDraft,
        start: backtestRange.start || null, end: backtestRange.end || null,
      },
    });
    setBacktest(result); setNotice('Causal backtest queued on the prediction service.');
  });
  const explainBacktest = () => perform(async () => {
    const result = backtest?.result || {};
    const utility = Object.fromEntries(['BUY', 'SELL', 'HOLD'].map((side) => [side, {
      count: result.policy_action_utility?.[side]?.evaluated_count,
      useful_rate: result.policy_action_utility?.[side]?.directionally_useful_rate,
      next_day_effect_usdt: result.policy_action_utility?.[side]?.estimated_next_day_effect_usdt,
    }]));
    const summary = {
      symbol: result.symbol, total_return_percent: result.total_return_percent,
      buy_hold_return_percent: result.buy_hold_return_percent,
      excess_return_vs_buy_hold_percent: result.excess_return_vs_buy_hold_percent,
      maximum_drawdown_percent: Number(result.maximum_drawdown) * 100,
      trade_count: result.trade_count, action_counts: result.action_counts,
      forecast_direction_diagnostics: result.forecast_direction_diagnostics,
      policy_action_utility: utility,
    };
    const reply = await agentApi({ command: 'trade', symbol, question:
      `Explain this paper-policy backtest. Separate direction quality, P&L, drawdown, and buy-and-hold comparison; identify risks and do not claim real-trading profitability. Data: ${JSON.stringify(summary)}` });
    setExplanation(reply.answer);
  });

  const pnl = Number(portfolio.equity_usdt || 0) - Number(portfolio.initial_cash_usdt || 0);
  const lastEquity = useMemo(() => equity.at(-1), [equity]);
  return <main className="paper-dashboard">
    <div className="paper-title"><div><p className="eyebrow">Research simulation</p><h1>Manual paper trading</h1>
      <p>Deterministic forecast policy, explicit confirmation, no exchange connectivity and no fee simulation.</p></div>
      <div className="paper-controls">
        {portfolios.length ? <select aria-label="Paper portfolio" value={portfolioId} onChange={(event) => setPortfolioId(event.target.value)}>
          {portfolios.map((item) => <option value={item.portfolio_id} key={item.portfolio_id}>{item.name}</option>)}</select>
          : <button className="button button-primary" disabled={busy} onClick={createPortfolio}>Create 100k portfolio</button>}
        <select aria-label="Trading symbol" value={symbol} onChange={(event) => { setSymbol(event.target.value); setPreview(null); }}><option>BTC</option><option>ETH</option></select>
        {portfolioId && <button className="button button-secondary" disabled={busy} onClick={() => perform(refresh)}>Refresh</button>}
      </div>
    </div>
    {error && <div className="error-banner" role="alert">{error}</div>}
    {notice && <div className="paper-notice" role="status">{notice}</div>}
    {!portfolioId ? <p className="paper-empty">Create a portfolio to start. All balances are simulated.</p> : <>
      <section className="paper-metrics">
        <Metric label="Equity" value={money(portfolio.equity_usdt)} detail={lastEquity ? `Last snapshot ${utc(lastEquity.observed_at, true)}` : 'Marked to latest closed minute'} />
        <Metric label="Cash" value={money(portfolio.cash_usdt)} />
        <Metric label="Total P&L" value={money(pnl)} tone={pnl >= 0 ? 'positive' : 'negative'} detail={percent(Number(portfolio.total_return || 0) * 100)} />
        <Metric label="Drawdown" value={percent(Number(portfolio.drawdown || 0) * 100)} tone={Number(portfolio.drawdown) < 0 ? 'negative' : ''} />
      </section>
      <PolicyEditor policy={policy} fields={policy?.fields} draft={policyDraft}
        onChange={changePolicy} onSave={savePolicy} onReset={resetPolicy}
        onBacktest={runBacktest} backtestRange={backtestRange}
        onRangeChange={changeBacktestRange} busy={busy} />
      <BacktestPanel job={backtest} explanation={explanation} onExplain={explainBacktest} busy={busy} />
      <div className="paper-grid">
        <DecisionPanel decision={decision} symbol={symbol} onCreate={createDecision} onPreview={previewOrder} busy={busy} />
        <section className="paper-card"><div className="paper-card-head"><div><p className="eyebrow">Portfolio</p><h2>Open positions</h2></div></div>
          {(portfolio.positions || []).length === 0 ? <p className="paper-empty">No open positions.</p> : <div className="paper-table-wrap"><table className="paper-table"><thead><tr><th>Asset</th><th>Quantity</th><th>Avg entry</th><th>Value</th><th>Unrealized</th></tr></thead><tbody>
            {portfolio.positions.map((row) => <tr key={row.symbol}><td>{row.symbol}</td><td>{amount(row.quantity, 8)}</td><td>{money(row.average_entry_price_usdt)}</td><td>{money(row.position_value_usdt)}</td><td className={Number(row.unrealized_pnl_usdt) >= 0 ? 'positive' : 'negative'}>{money(row.unrealized_pnl_usdt)}</td></tr>)}
          </tbody></table></div>}
        </section>
      </div>
      <section className="paper-card"><div className="paper-card-head"><div><p className="eyebrow">Forecast visualization</p><h2>{symbol} daily candles + next-close quantiles</h2></div></div>
        <ForecastCandleChart dailyCandles={candles.daily} hourlyCandles={candles.hourly} decision={decision} />
      </section>
      <section className="paper-card"><div className="paper-card-head"><div><p className="eyebrow">Performance</p><h2>Equity curve</h2></div></div><EquityChart rows={equity} /></section>
      <TradeAnalytics analytics={analytics} />
      <section className="paper-card"><div className="paper-card-head"><div><p className="eyebrow">Audit trail</p><h2>Paper fills</h2></div></div>
        {!orders.length ? <p className="paper-empty">No fills yet.</p> : <div className="paper-table-wrap"><table className="paper-table"><thead><tr><th>Time</th><th>Side</th><th>Asset</th><th>Quantity</th><th>Fill</th><th>Notional</th><th>Slippage</th></tr></thead><tbody>
          {orders.map((row) => <tr key={row.order_id}><td>{utc(row.executed_at, true)}</td><td className={row.side === 'BUY' ? 'positive' : 'negative'}>{row.side}</td><td>{row.symbol}</td><td>{amount(row.quantity, 8)}</td><td>{money(row.fill_price_usdt)}</td><td>{money(row.notional_usdt)}</td><td>{amount(row.slippage_bps, 1)} bps</td></tr>)}
        </tbody></table></div>}
      </section>
    </>}
    <ConfirmOrder preview={preview} busy={busy} onCancel={() => setPreview(null)} onConfirm={confirmOrder} />
  </main>;
}
