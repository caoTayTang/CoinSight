import React,{lazy,Suspense,useState,useId} from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {RESPONSE_LIMIT,safeResponseUrl,redactResponse,responseLimits} from './responsePolicy.js';
import ResponseCharts from './ResponseCharts.jsx';
import AgentTrace,{modelsUsed} from './AgentTrace.jsx';
import {skillSources,citationLinks,skillLabel} from './skillCitations.js';
import {COMMAND_HREF,commandLinks} from './commandTokens.js';
import {readableTimes} from './format.js';
import {CommandChip} from './CommandText.jsx';
const Diagram=lazy(()=>import('./ResponseDiagram.jsx'));
function ResponseCode({children}) {
  const child=React.Children.toArray(children)[0];
  const code=String(child?.props?.children||'').replace(/\n$/,'');
  const language=child?.props?.className?.replace('language-','')||'text';
  const [copied,setCopied]=useState(false),[failed,setFailed]=useState(false);
  if(language==='mermaid')return <Suspense fallback={<p>Loading diagram renderer…</p>}><Diagram code={code}/></Suspense>;
  return <div className="response-code"><header><span>{language}</span><button type="button" onClick={async()=>{
    try{await navigator.clipboard.writeText(code);setCopied(true);setFailed(false);setTimeout(()=>setCopied(false),1500);}catch{setFailed(true);}
  }}>{copied?'Copied':failed?'Copy unavailable':'Copy code'}</button></header><pre><code>{code}</code></pre></div>;
}
const components={
  pre:ResponseCode,
  table:({children})=><div className="response-table" tabIndex={0} aria-label="Response table; scroll horizontally if needed"><table>{children}</table></div>,
  a:({href,children})=>{const safe=safeResponseUrl(href);return safe?<a href={safe} {...(/^https?:/.test(safe)?{target:'_blank',rel:'noopener noreferrer',referrerPolicy:'no-referrer'}:{})}>{children}</a>:<span className="response-blocked-link" title="Unsafe or credential-bearing link removed">{children} <small>[link removed]</small></span>;},
  input:({checked})=><input type="checkbox" checked={Boolean(checked)} disabled aria-label={checked?'Completed item':'Incomplete item'}/>,
};
// When the answer was made: its times like "08:46 UTC" are read relative to this.
function answerTime(meta) {
  const stamp = meta?.created_at || meta?.evidence?.find(e => e?.result?.observed_at)?.result?.observed_at;
  const parsed = Date.parse(stamp);
  return Number.isNaN(parsed) ? Date.now() : parsed;
}
export default function AgentResponse({text,meta,onCommand}) {
  const prefix = 'skill-' + useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const sources = skillSources(meta?.evidence);
  const links = new Map(sources.map((s,i) => [s.citation, `#${prefix}-${i}`]));
  const sourceTargets = new Set(links.values());
  const descriptions = new Map(sources.map((s,i) => [`#${prefix}-${i}`, s.description]));
  const responseComponents = {...components, a: props => {
    if (props.href?.startsWith(COMMAND_HREF)) return <CommandChip token={props.href.slice(COMMAND_HREF.length)} onCommand={onCommand}/>;
    if (!sourceTargets.has(props.href)) return components.a(props);
    return <a className="runbook-citation" href={props.href} title={`Skill followed: ${descriptions.get(props.href)} Click to read it.`} onClick={event => {
      event.preventDefault();
      const source = document.getElementById(props.href.slice(1));
      if (source) { source.open = true; source.focus(); source.scrollIntoView({block:'nearest'}); }
    }}>Skill · {props.children}</a>;
  }};
  const clean=redactResponse(text),truncated=clean.length>RESPONSE_LIMIT;
  const policy=meta?.guardrails;
  const models=meta?modelsUsed(meta):[];
  return <div className="agent-response">
    {meta&&<div className={`response-evidence-badge ${policy?.evidence_status||'available'}`}><span>{meta.llm_calls===0?'DIRECT TOOL':'AGENT EXPLANATION'}</span><span>{policy?.evidence_status?`Evidence: ${policy.evidence_status}`:meta.llm_calls===0?'Source values attached':'Review tool evidence below'}</span></div>}
    {models.length>0&&<p className="response-model" title="Model selected by the router">Model · {models.join(' → ')}</p>}
    {meta&&<AgentTrace meta={meta}/>}
    <div className="chat-markdown response-prose"><Markdown remarkPlugins={[remarkGfm,responseLimits,citationLinks(links),commandLinks,readableTimes(answerTime(meta))]} skipHtml disallowedElements={['img','iframe','script','style','video','audio','object','embed']} urlTransform={safeResponseUrl} components={responseComponents}>{clean.slice(0,RESPONSE_LIMIT)}</Markdown></div>
    {truncated&&<p className="response-warning" role="status">Response display truncated at {RESPONSE_LIMIT.toLocaleString()} characters.</p>}
    {policy?.warnings?.length>0&&<aside className="response-warning" aria-label="Response limitations"><strong>Evidence limits</strong><ul>{policy.warnings.map((w,i)=><li key={i}>{w}</li>)}</ul></aside>}
    {sources.length>0&&<section className="runbook-sources" aria-label="Skills followed">
      <h3>Skills followed <span>{sources.length}</span></h3>
      <p>Instructions the agent loaded for this answer · they describe how to investigate, not the current state.</p>
      {sources.map((s,i)=><details id={`${prefix}-${i}`} tabIndex={-1} key={s.citation}>
        <summary>{skillLabel(s.citation)}</summary>
        <p>{redactResponse(s.description)}</p>
        <blockquote>{redactResponse(s.text)}</blockquote>
        <dl><dt>Source</dt><dd>{redactResponse(s.source)}</dd><dt>SHA-256</dt><dd>{s.sha256}</dd></dl>
      </details>)}
    </section>}
    <ResponseCharts meta={meta}/>
  </div>;
}
