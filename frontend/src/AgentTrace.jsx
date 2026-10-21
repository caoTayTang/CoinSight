import React from 'react';
import {redactResponse} from './responsePolicy.js';

const duration=ms=>ms==null?'':ms<1000?`${ms} ms`:`${(ms/1000).toFixed(1)} s`;
const tokenCount=usage=>(usage?.inputTokens||0)+(usage?.outputTokens||0);
const json=value=>redactResponse(JSON.stringify(value??null,null,2));
export const shortModel=model=>String(model||'').split('/').pop();

// Models that answered, in call order, each with the route slots it used: ['gpt-oss-120b · groq#1, groq#2'].
export function modelsUsed(meta) {
  const selected=(meta?.steps?.length?meta.steps.map(s=>s.model):(meta?.routing||[]).map(r=>r.selected)).filter(Boolean);
  const slots=new Map();
  for (const m of selected) slots.set(m.model,[...new Set([...(slots.get(m.model)||[]),m.route])]);
  return [...slots].map(([model,routes])=>`${shortModel(model)} · ${routes.join(', ')}`);
}

// Direct ML commands make no model call; show their tool evidence as a single step.
function stepsOf(meta) {
  if (meta?.steps?.length) return meta.steps;
  const evidence=Array.isArray(meta?.evidence)?meta.evidence:[];
  return evidence.length?[{step:1,kind:'direct',tools:evidence.map((e,i)=>({name:e.tool||'tool',arguments:e.arguments,
    status:e.result?.status==='unavailable'?'error':'success',evidence:i}))}]:[];
}

function ToolCall({tool,evidence}) {
  const output=evidence?.[tool.evidence]?.result;
  return <details className={`trace-tool ${tool.status||'pending'}`}>
    <summary><code>{tool.name}</code><span className="trace-tool-status">{tool.status==='error'?'failed':tool.status==='success'?'ok':'not run'}</span>{tool.latency_ms!=null&&<span>{duration(tool.latency_ms)}</span>}</summary>
    <h5>Input</h5><pre>{json(tool.arguments||{})}</pre>
    <h5>Output</h5>{output===undefined?<p>No output recorded.</p>:<pre>{json(output)}</pre>}
  </details>;
}

function Step({step,evidence}) {
  const tools=step.tools||[];
  const title=step.kind==='budget_exhausted'?'Step budget exhausted':step.kind==='direct'?'Direct tool call · no model'
    :tools.length?`Called ${tools.map(t=>t.name).join(', ')}`:'Wrote the answer';
  const tokens=tokenCount(step.usage);
  return <li><details>
    <summary><span className="trace-step-index">{step.step}</span><span className="trace-step-title">{title}</span>
      <span className="trace-step-meta">{[step.model&&`${shortModel(step.model.model)} · ${step.model.route}`,duration(step.latency_ms),tokens?`${tokens.toLocaleString()} tok`:''].filter(Boolean).join(' · ')}</span></summary>
    <div className="trace-step-body">
      {step.fallbacks?.length>0&&<p className="trace-fallbacks">Fallback: {step.fallbacks.map(a=>`${a.route} ${a.status==='http_error'?a.http_status:a.status}${a.cooldown_seconds?` (rests ${a.cooldown_seconds} s)`:''}`).join(' → ')} → {step.model?.route}</p>}
      {step.reasoning&&<details className="trace-reasoning"><summary>Reasoning</summary><pre>{redactResponse(step.reasoning)}</pre></details>}
      {step.text&&tools.length>0&&<p className="trace-note">{redactResponse(step.text)}</p>}
      {tools.map((tool,i)=><ToolCall key={i} tool={tool} evidence={evidence}/>)}
      {!tools.length&&!step.reasoning&&step.kind==='model'&&<p className="trace-note">No tools called in this step.</p>}
    </div>
  </details></li>;
}

export default function AgentTrace({meta}) {
  const steps=stepsOf(meta);
  if (!steps.length) return null;
  const toolCount=steps.reduce((n,s)=>n+(s.tools?.length||0),0);
  const total=steps.reduce((n,s)=>n+(s.latency_ms||0)+(s.tools||[]).reduce((m,t)=>m+(t.latency_ms||0),0),0);
  return <details className="agent-trace">
    <summary>{steps.length} step{steps.length===1?'':'s'} · {toolCount} tool call{toolCount===1?'':'s'}{total?` · ${duration(total)}`:''}</summary>
    <ol>{steps.map(step=><Step key={step.step} step={step} evidence={meta.evidence}/>)}</ol>
  </details>;
}
