// Desk conversation state that outlives a page load: the open thread and the picked model.
const THREAD_KEY='coinsight.thread.v1', MODEL_KEY='coinsight.model.v1';
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export const newThreadId=()=>crypto.randomUUID();
function read(key,valid) { try { const v=localStorage.getItem(key); return valid(v)?v:null; } catch { return null; } }
function write(key,value) { try { value==null?localStorage.removeItem(key):localStorage.setItem(key,value); } catch {} }
export const storedThread=()=>read(THREAD_KEY,v=>UUID.test(v||''));
export const rememberThread=id=>write(THREAD_KEY,id);
export const storedModel=()=>read(MODEL_KEY,v=>/^[a-zA-Z0-9_-]{1,64}$/.test(v||''));
export const rememberModel=name=>write(MODEL_KEY,name==='auto'?null:name);

// How the user typed a stored run, so a reopened thread reads like it did.
export function promptOf(run) {
  if (run.command==='sre') return `@sre ${run.question}`;
  if (['predict','anomaly','drift'].includes(run.command)) return `/${run.command} ${run.symbol}`;
  return run.question;
}

// Stored runs (GET /v1/agent/threads/{id}) back into chat messages, including each answer's step trace.
export function runsToMessages(runs=[]) {
  return runs.flatMap(run=>[
    {role:'user',text:promptOf(run)},
    run.status==='ok'
      ?{role:'agent',text:run.answer||'',commandMeta:{...run,command:run.command}}
      :{role:'agent error',text:run.error||'This request failed.'},
  ]);
}

// One picker line: label, then measured eval results when the model has been evaluated.
export function modelOptionLabel(route) {
  const e=route.eval, parts=[route.label];
  if (e?.pass_rate!=null) parts.push(`${Math.round(e.pass_rate*100)}% eval`);
  if (e?.latency_p50_ms!=null) parts.push(`${(e.latency_p50_ms/1000).toFixed(1)} s`);
  if (!route.available) parts.push('no key');
  else if (route.allowed === false) parts.push('not available to you now');
  return parts.join(' · ');
}
