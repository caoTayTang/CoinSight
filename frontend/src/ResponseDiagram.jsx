import React,{useEffect,useId,useRef,useState} from 'react';
import DOMPurify from 'dompurify';
import {diagramPolicy,SVG_SANITIZE} from './responsePolicy.js';
let engine;
const load=()=>engine ||= import('mermaid').then(({default:m})=>{
  m.initialize({startOnLoad:false,securityLevel:'strict',suppressErrorRendering:true,maxTextSize:8000,maxEdges:80,
    flowchart:{htmlLabels:false},theme:'base',themeVariables:{primaryColor:'#1c2e4b',primaryTextColor:'#d9e7ff',primaryBorderColor:'#7c9ed1',lineColor:'#819dc7',fontFamily:'Plus Jakarta Sans, sans-serif'}});
  return m;
});
export default function ResponseDiagram({code}) {
  const id='response-diagram-'+useId().replace(/[^a-z0-9]/gi,'');
  const policy=diagramPolicy(code);
  const [markup,setMarkup]=useState(''),[error,setError]=useState(''),[zoom,setZoom]=useState(1);
  const output=useRef(null);
  useEffect(()=>{
    let active=true;setMarkup('');setError('');
    if(!policy.allowed)return;
    load().then(m=>m.render(id,policy.code)).then(r=>{
      const clean=DOMPurify.sanitize(r.svg,SVG_SANITIZE);
      if(!clean.includes('<svg'))throw new Error('Empty sanitized diagram');
      if(active)setMarkup(clean);
    }).catch(()=>{if(active)setError('Diagram syntax could not be rendered. The source remains available below.');});
    return ()=>{active=false;};
  },[code,id]);
  return <figure className="response-diagram">
    <figcaption><strong>Explanation diagram</strong><span>Schematic · not measured data</span></figcaption>
    {!policy.allowed?<p className="response-warning">{policy.reason}</p>:error?<p role="status">{error}</p>:markup?<>
      <div className="response-diagram-controls"><button type="button" onClick={()=>setZoom(z=>Math.max(.5,z-.25))} disabled={zoom<=.5} aria-label="Zoom diagram out">−</button><output>{Math.round(zoom*100)}%</output><button type="button" onClick={()=>setZoom(z=>Math.min(3,z+.25))} disabled={zoom>=3} aria-label="Zoom diagram in">+</button><button type="button" onClick={()=>setZoom(1)}>Reset</button></div>
      <div className="response-diagram-scroll" tabIndex={0} aria-label="Explanation diagram; scroll to inspect"><div ref={output} style={{width:zoom===1?'100%':`${zoom*100}%`,minWidth:zoom>1?'100%':undefined}} dangerouslySetInnerHTML={{__html:markup}}/></div>
    </>:<p role="status">Drawing diagram…</p>}
    <details><summary>Diagram source</summary><pre><code>{code}</code></pre></details>
  </figure>;
}
