import React from 'react';
import {evidenceCharts} from './responsePolicy.js';
import {when} from './format.js';
export default function ResponseCharts({meta}) {
  const charts=evidenceCharts(meta);
  if(!charts.length)return null;
  return <section className="response-charts" aria-label="Charts from tool evidence">{charts.map((chart,i)=>{
    const maximum=Math.max(...(chart.rows||[]).map(r=>r.value+(r.offset||0)),chart.reference||0,1e-9)*1.08;
    const format=n=>new Intl.NumberFormat('en-US',{maximumFractionDigits:chart.unit==='hours'?0:chart.unit==='USDT'?2:4}).format(n);
    return <figure className="response-chart" key={i}><figcaption><strong>{chart.title}</strong><span>{chart.rows?`Tool evidence · ${chart.unit}`:`From ${chart.source}`}</span></figcaption>
      {chart.kind==='breakdown'?<TimeBreakdown b={chart.breakdown}/>:chart.kind==='drift'?<DriftView d={chart.drift}/>:
      chart.kind==='comparison'?<div className="response-comparison">{chart.rows.map(r=><div className={r.estimate?'estimate':''} key={r.label}>
        <span>{r.estimate?<em className="forecast-tag">Forecast</em>:r.label}{r.at?`${r.estimate?'for':' ·'} ${when(r.at)}`:''}</span>
        <strong>{format(r.value)} <small>{chart.unit}</small></strong>
        {r.estimate&&chart.move!=null&&<b className={chart.move>=0?'positive':'negative'}>{chart.move>=0?'+':''}{chart.move.toFixed(2)}% expected</b>}
      </div>)}</div>:
      chart.rows&&<div className="response-bars" role="img" aria-label={chart.rows.map(r=>`${r.label}: ${format(r.value)} ${chart.unit}`).join('; ')}>{chart.rows.map((r,j)=><div className="response-bar-row" key={j}><span title={r.label}>{r.warning?'! ':''}{r.label}</span><div className="response-bar-track"><i className={`${r.reference?'reference':''} ${r.warning?'warning':''}`} style={{width:`${r.value/maximum*100}%`,marginLeft:r.offset?`${r.offset/maximum*100}%`:undefined}}/>{chart.reference!=null&&<b className="response-threshold" style={{left:`${chart.reference/maximum*100}%`}}/>}</div><output>{format(r.value)}</output></div>)}</div>}
      {chart.reference!=null&&<p className="response-chart-legend">Dashed marker: PSI watch at {chart.reference}</p>}
      <p className="response-chart-note">{chart.interpretation}</p><small>{chart.source}{chart.cutoff?` · data up to ${when(chart.cutoff)}`:''}</small>
      {chart.rows&&<details><summary>Exact values</summary><table><thead><tr><th>Metric</th><th>Value ({chart.unit})</th></tr></thead><tbody>{chart.rows.map(r=><tr key={r.label}><td>{r.label}</td><td>{String(r.value)}</td></tr>)}</tbody></table></details>}
      {chart.drift&&<details><summary>All inputs (technical)</summary><table><thead><tr><th>Feature</th><th>PSI</th></tr></thead><tbody>{chart.drift.all.map(r=><tr key={r.feature}><td>{r.feature}</td><td>{r.psi}</td></tr>)}</tbody></table></details>}
    </figure>;
  })}</section>;
}

const seconds=ms=>`${(ms/1000).toFixed(ms<10000?1:0)} s`;
function TimeBreakdown({b}) {
  return <div className="time-breakdown">
    <p><strong>{seconds(b.total)}</strong> in total · {b.modelCalls} model answer{b.modelCalls===1?'':'s'}</p>
    <div className="time-stack" role="img" aria-label={b.parts.map(p=>`${p.label} ${seconds(p.ms)}`).join(', ')}>
      {b.parts.map(p=><i key={p.key} className={p.key} style={{width:`${p.ms/b.total*100}%`}} title={`${p.label}: ${seconds(p.ms)}`}/>)}
    </div>
    <ul className="time-legend">{b.parts.map(p=><li key={p.key}><i className={p.key}/>{p.label}<b>{seconds(p.ms)}</b></li>)}</ul>
    {b.failedAttempts.length>0&&<p className="time-note">Retries before an answer: {b.failedAttempts.map(a=>`${a.label} ×${a.count}`).join(', ')}.</p>}
    {b.slowestTool&&<p className="time-note">Slowest tool: {b.slowestTool.name}, {seconds(b.slowestTool.ms)}.</p>}
  </div>;
}

const LEVEL={stable:'Stable',shifting:'Shifting',changed:'Changed'};
function DriftView({d}) {
  return <div className={`drift-view ${d.verdict}`}>
    <p className="drift-verdict"><em>{LEVEL[d.verdict]}</em>{d.headline}</p>
    <h4>Inputs that moved most</h4>
    <ul>{d.top.map(r=><li key={r.feature}><span>{r.label}</span>
      <div className="drift-track" title={`PSI ${r.psi} of watch level 0.25`}><i className={r.level} style={{width:`${r.share*100}%`}}/></div>
      <b className={r.level}>{LEVEL[r.level]}</b></li>)}</ul>
    <small>Full bar = watch level. Under half is normal day-to-day change.</small>
  </div>;
}
