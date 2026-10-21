import React from 'react';
import {evidenceCharts} from './responsePolicy.js';
export default function ResponseCharts({meta}) {
  const charts=evidenceCharts(meta);
  if(!charts.length)return null;
  return <section className="response-charts" aria-label="Charts from tool evidence">{charts.map((chart,i)=>{
    const maximum=Math.max(...chart.rows.map(r=>r.value+(r.offset||0)),chart.reference||0,1e-9)*1.08;
    const format=n=>new Intl.NumberFormat('en-US',{maximumFractionDigits:chart.unit==='hours'?0:chart.unit==='USDT'?2:4}).format(n);
    return <figure className="response-chart" key={i}><figcaption><strong>{chart.title}</strong><span>Tool evidence · {chart.unit}</span></figcaption>
      {chart.kind==='comparison'?<div className="response-comparison">{chart.rows.map(r=><div className={r.estimate?'estimate':''} key={r.label}><span>{r.label}{r.estimate?' · estimate':''}</span><strong>{format(r.value)} <small>{chart.unit}</small></strong></div>)}</div>:
      <div className="response-bars" role="img" aria-label={chart.rows.map(r=>`${r.label}: ${format(r.value)} ${chart.unit}`).join('; ')}>{chart.rows.map((r,j)=><div className="response-bar-row" key={j}><span title={r.label}>{r.warning?'! ':''}{r.label}</span><div className="response-bar-track"><i className={`${r.reference?'reference':''} ${r.warning?'warning':''}`} style={{width:`${r.value/maximum*100}%`,marginLeft:r.offset?`${r.offset/maximum*100}%`:undefined}}/>{chart.reference!=null&&<b className="response-threshold" style={{left:`${chart.reference/maximum*100}%`}}/>}</div><output>{format(r.value)}</output></div>)}</div>}
      {chart.reference!=null&&<p className="response-chart-legend">Dashed marker: PSI watch at {chart.reference}</p>}
      <p className="response-chart-note">{chart.interpretation}</p><small>{chart.source}{chart.cutoff?` · ${chart.cutoff}`:''}</small>
      {chart.traceId&&<a className="trace-inspect-link" href={`http://127.0.0.1:16686/trace/${chart.traceId}`} target="_blank" rel="noopener noreferrer">Open trace in local Jaeger ↗</a>}
      <details><summary>Exact values</summary><table><thead><tr><th>Metric</th><th>Value ({chart.unit})</th></tr></thead><tbody>{chart.rows.map(r=><tr key={r.label}><td>{r.label}</td><td>{String(r.value)}</td></tr>)}</tbody></table></details>
    </figure>;
  })}</section>;
}
