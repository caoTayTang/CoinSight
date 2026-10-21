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
    const rows=value.spans.filter(s=>s&&finite(s.duration_ms)&&s.duration_ms>=0&&finite(s.offset_ms)&&s.offset_ms>=0)
      .slice(0,24).map(s=>({label:`${s.service} · ${s.operation}`,value:s.duration_ms,offset:s.offset_ms,warning:s.error===true}));
    if(!rows.length)return null;
    return {kind:'timeline',title:'Request trace',unit:'ms',cutoff:value.started_at,source:'Jaeger · inspect_trace',
      traceId:/^[a-f0-9]{32}$/.test(value.trace_id)?value.trace_id:null,rows,
      interpretation:`Observed spans can overlap; durations must not be summed. ${value.spans_truncated||value.spans.length>24?'Display is truncated. ':''}Error spans identify observations, not a proven root cause.`};
  }
  if(name==='detect_market_anomaly'||name==='anomaly') {
    const r=value.trained;
    if(!r||![r.score,r.threshold].every(finite)||r.score<0||r.threshold<0) return null;
    return {kind:'bar',title:'Closed-hour anomaly score',unit:'score',cutoff:r.cutoff,source:'Isolation Forest tool',
      interpretation:'Higher = more unusual. Threshold is a rule, not a crash probability.',
      rows:[{label:'Forest score',value:r.score},{label:'Frozen threshold',value:r.threshold,reference:true}]};
  }
  if(name==='model_health'||name==='drift') {
    const rows=(Array.isArray(value.data_drift)?value.data_drift:[]).filter(r=>r&&typeof r.feature==='string'&&finite(r.psi)&&r.psi>=0).slice(0,10)
      .map(r=>({label:r.feature,value:r.psi}));
    if(!rows.length) return null;
    return {kind:'bar',title:'Feature distribution drift',unit:'PSI',cutoff:value.source?.cutoff,source:'model_health tool',reference:.25,
      interpretation:'PSI 0.25 is a heuristic watch threshold, not forecast MAE or a significance test.',rows};
  }
  if(name==='predict_hourly'||name==='predict') {
    const r=value.result||value;
    if(!finite(r.reference_close_usdt)||!finite(r.predicted_close_usdt)||r.reference_close_usdt<=0||r.predicted_close_usdt<=0) return null;
    return {kind:'comparison',title:'Reference vs predicted close',unit:'USDT',cutoff:r.cutoff,source:'Frozen CatBoost ensemble',
      interpretation:'Two values, not a historical price path. Predicted close is a model estimate.',
      rows:[{label:'Reference close',value:r.reference_close_usdt},{label:'Predicted close',value:r.predicted_close_usdt,estimate:true}]};
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
