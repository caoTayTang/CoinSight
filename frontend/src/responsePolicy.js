import {traceBreakdown,driftSummary} from './answerViews.js';
// Only rendering/data policy lives here. It never decides whether to execute a tool.
export const RESPONSE_LIMIT = 30000;
export function safeResponseUrl(value) {
  if (typeof value!=='string' || /[\u0000-\u0020\u007f\\]/.test(value)) return undefined;
  if (value.startsWith('#')) return value;
  if (value==='/' || /^\/(?:docs|reports)(?:\/|$)/.test(value)) return value;
  try {
    const u=new URL(value);
    if (!['https:','http:'].includes(u.protocol) || u.username || u.password) return undefined;
    if ([...u.searchParams.keys()].some(k=>/token|secret|api.?key|authorization|signature/i.test(k))) return undefined;
    return u.href;
  } catch { return undefined; }
}
export function secretLike(text) {
  return /(?:sk-or-v1-|gsk_|ABSK)[A-Za-z0-9_+/=.-]{16,}/.test(String(text));
}
export function redactResponse(text) {
  return String(text||'').replace(/(?:sk-or-v1-|gsk_|ABSK)[A-Za-z0-9_+/=.-]{16,}/g,'[credential redacted]');
}
export function diagramPolicy(code) {
  const value=String(code).trim();
  if (value.length>8000 || value.split('\n').length>100) return {allowed:false,reason:'Diagram exceeds the size limit.'};
  if (!/^(?:flowchart\s+(?:TD|TB|LR|RL|BT)|graph\s+(?:TD|TB|LR|RL|BT)|sequenceDiagram|stateDiagram-v2)\b/.test(value))
    return {allowed:false,reason:'Only flowchart, sequence and state diagrams are enabled.'};
  if (/%%\s*\{|@\s*\{|^---|\b(?:click|href|callback|classDef|linkStyle|style)\b|<[^>]*>|(?:https?:|javascript:|data:|file:)|@import|url\s*\(/im.test(value))
    return {allowed:false,reason:'Interactive links, directives, HTML and custom styles are disabled.'};
  const edges=value.match(/-->|---|==>|-\.->|->>|-->>|:>/g)||[];
  if(edges.length>80) return {allowed:false,reason:'Too many diagram edges.'};
  return {allowed:true,code:value};
}
export const SVG_SANITIZE = {
  USE_PROFILES:{svg:true,svgFilters:true},
  FORBID_TAGS:['script','foreignObject','iframe','image','a','animate','animateMotion','animateTransform','set'],
  FORBID_ATTR:['href','xlink:href','target','formaction'],
  ALLOW_DATA_ATTR:false,
};
const finite=n=>typeof n==='number'&&Number.isFinite(n);
function chartFromResult(value,name) {
  if(!value||typeof value!=='object') return null;
  if(name==='inspect_trace'&&value.status==='available'&&Array.isArray(value.spans)) {
    const breakdown=traceBreakdown(value);
    if(!breakdown)return null;
    return {kind:'breakdown',title:'Where the time went',unit:'s',cutoff:value.started_at,source:'Jaeger trace',breakdown,
      interpretation:'Spans overlap, so only the parts the user waited for are shown. Failed attempts are retries before a model answered.'};
  }
  if(name==='detect_market_anomaly'||name==='anomaly') {
    const rows=['hourly','daily'].map(period=>({period,value:value?.[period]}))
      .filter(({value:r})=>r&&[r.score,r.threshold].every(finite)&&r.score>=0&&r.threshold>=0);
    if(rows.length) return {kind:'bar',title:`${value.symbol||''} market anomaly scores`.trim(),unit:'score',cutoff:value.observed_at,source:'Pinned Isolation Forest bundles',
        interpretation:'Higher = more unusual. Threshold is a rule, not a crash probability.',
        rows:rows.flatMap(({period,value:r})=>[
          {label:`${period} score`,value:r.score,warning:r.is_anomaly===true},
          {label:`${period} threshold`,value:r.threshold,reference:true},
        ])};
    // Backward-compatible rendering for legacy single-frequency evidence.
    const r=value.trained;
    if(!r||![r.score,r.threshold].every(finite)||r.score<0||r.threshold<0) return null;
    const unusual=r.score>=r.threshold;
    return {kind:'gauge',title:'Was the last hour unusual?',unit:'score',cutoff:r.cutoff,source:'Isolation Forest',
      gauge:{verdict:unusual?'Unusual':'Normal',tone:unusual?'changed':'stable',share:Math.min(1,r.score/(r.threshold*1.5)),mark:1/1.5,
        text:unusual?'This hour stands out from recent trading and crossed the alert level.':
          `This hour looks like normal trading: ${Math.round(r.score/r.threshold*100)}% of the way to the alert level.`},
      interpretation:'Unusual is not the same as a crash or bad data; it means worth a look.',
      rows:[{label:'Unusualness score',value:r.score},{label:'Alert level',value:r.threshold}]};
  }
  if(name==='model_health'||name==='drift') {
    const drift=driftSummary(value.data_drift);
    if(!drift) return null;
    return {kind:'drift',title:'Are market inputs still like the training data?',unit:'PSI',cutoff:value.source?.cutoff,source:'model_health tool',drift,
      interpretation:'Drift is a warning sign, not proof the forecast got worse.'};
  }
  if(name==='forecast_support'||name==='predict') {
    const r=value.result||value;
    const f=r.forecast;
    if(f&&[f.reference_close_usdt,f.predicted_close_q10_usdt,f.predicted_close_q50_usdt,f.predicted_close_q90_usdt].every(finite)&&
      [f.reference_close_usdt,f.predicted_close_q10_usdt,f.predicted_close_q50_usdt,f.predicted_close_q90_usdt].every(v=>v>0))
      return {kind:'comparison',title:`${r.symbol||''} next daily close forecast`.trim(),unit:'USDT',cutoff:f.target_open,source:'Pinned daily forecast bundle',
        interpretation:'q10–q90 is an empirical model interval, not guaranteed confidence or a historical path.',
        rows:[{label:'Last closed day',value:f.reference_close_usdt},{label:'q10',value:f.predicted_close_q10_usdt,estimate:true},
          {label:'q50',value:f.predicted_close_q50_usdt,estimate:true},{label:'q90',value:f.predicted_close_q90_usdt,estimate:true}]};
    // Backward-compatible rendering for the legacy hourly point forecast.
    if(!finite(r.reference_close_usdt)||!finite(r.predicted_close_usdt)||r.reference_close_usdt<=0||r.predicted_close_usdt<=0) return null;
    return {kind:'comparison',title:'Now vs forecast',unit:'USDT',cutoff:r.cutoff,source:'Frozen CatBoost ensemble',
      interpretation:'The forecast is a model estimate, not a price that happened.',
      move:finite(r.expected_move_pct)?r.expected_move_pct:(r.predicted_close_usdt/r.reference_close_usdt-1)*100,
      rows:[{label:'Last close',value:r.reference_close_usdt,at:r.cutoff},{label:'Forecast',value:r.predicted_close_usdt,estimate:true,at:r.target_close}]};
  }
  if(name==='warehouse_coverage') {
    const r=value.rows?.[0];
    if(!r||![r.expected_hours,r.observed_hours,r.missing_hours].every(finite)||
      r.expected_hours<0||r.observed_hours<0||r.missing_hours<0||r.observed_hours+r.missing_hours!==r.expected_hours) return null;
    return {kind:'bar',title:'Warehouse closed-hour coverage',unit:'hours',cutoff:value.observed_at,source:'warehouse_coverage tool',
      interpretation:'A coverage count at the requested asset/source grain, not a whole-system health score.',
      rows:[{label:'Expected',value:r.expected_hours,reference:true},{label:'Observed',value:r.observed_hours},{label:'Missing',value:r.missing_hours,warning:r.missing_hours>0}]};
  }
  return null;
}
export function evidenceCharts(meta) {
  if(!meta) return [];
  const result=[];
  const add=(data,name)=>{const chart=chartFromResult(data,name);if(chart)result.push(chart);};
  if(['predict','anomaly','drift'].includes(meta.command)) add(meta.evidence,meta.command);
  const walk=(entries,depth=0)=>{
    if(depth>3||!Array.isArray(entries))return;
    for(const e of entries.slice(0,16)) {
      const v=e?.result;
      if(v?.status==='unavailable'||v?.status==='truncated')continue;
      add(v,e?.tool);
      if(e?.tool==='investigate_warehouse')walk(v?.result?.evidence,depth+1);
    }
  };
  if(Array.isArray(meta.evidence))walk(meta.evidence);
  const seen=new Set();return result.filter(c=>{const k=c.title+String(c.cutoff);if(seen.has(k))return false;seen.add(k);return true;}).slice(0,4);
}
export function responseLimits() {
  return tree=>{
    let diagrams=0,blocks=0;
    const walk=node=>{
      if(!Array.isArray(node.children))return;
      const children=[];
      for(const child of node.children){
        if(child.type==='code') {
          blocks++;
          if(child.lang==='mermaid')diagrams++;
          if(blocks>12||(child.lang==='mermaid'&&diagrams>2)){
            children.push({type:'paragraph',children:[{type:'text',value:'Additional code or diagram omitted by the response display limit.'}]});continue;
          }
        }
        let tableTrimmed=false;
        if(child.type==='table'){
          tableTrimmed=child.children.length>101||child.children.some(row=>row.children.length>12);
          if(child.children.length>101)child.children=child.children.slice(0,101);
          child.children.forEach(row=>{row.children=row.children.slice(0,12);});
        }
        walk(child);children.push(child);
        if(tableTrimmed)children.push({type:'paragraph',children:[{type:'text',value:'Table display limited to 100 data rows and 12 columns.'}]});
      }
      node.children=children;
    };
    walk(tree);
  };
}
