import React, { useEffect, useId, useRef, useState } from 'react';

let mermaidPromise;
function loadMermaid() {
  return mermaidPromise ||= import('mermaid').then(({ default: mermaid }) => {
    mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'base',
      themeVariables: { primaryColor: '#e7f3ed', primaryTextColor: '#183a32', primaryBorderColor: '#73978c', lineColor: '#55756c', fontFamily: 'Plus Jakarta Sans, sans-serif' } });
    return mermaid;
  });
}

export default function Diagram({ code }) {
  const id = `diagram-${useId().replace(/[^a-z0-9]/gi, '')}`;
  const [svg, setSvg] = useState('');
  const [failed, setFailed] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [naturalWidth, setNaturalWidth] = useState(1200);
  const [expanded, setExpanded] = useState(false);
  const dialog = useRef(null);
  const viewport = useRef(null);
  const drag = useRef(null);
  const changeZoom = (value) => setZoom(Math.max(.1, Math.min(4, value)));
  useEffect(() => {
    let active = true;
    loadMermaid().then(async (m) => {
      await document.fonts.ready;
      const result = await m.render(id, code);
      if (active) {
        const viewBox = result.svg.match(/viewBox="([^"]+)"/)?.[1].split(/\s+/).map(Number);
        if (viewBox && Number.isFinite(viewBox[2]) && viewBox[2] > 0) setNaturalWidth(viewBox[2]);
        setSvg(result.svg);
      }
    }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [code, id]);
  useEffect(() => {
    if (svg && !expanded && viewport.current) setZoom(Math.max(.1, Math.min(1, (viewport.current.clientWidth - 40) / naturalWidth)));
  }, [svg, expanded, naturalWidth]);
  useEffect(() => {
    if (expanded) dialog.current.showModal();
    else dialog.current.close();
    const previous = document.body.style.overflow;
    if (expanded) document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = previous; };
  }, [expanded]);
  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const wheel = (event) => {
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        setZoom((value) => Math.max(.1, Math.min(4, value + (event.deltaY < 0 ? .1 : -.1))));
      }
    };
    element.addEventListener('wheel', wheel, { passive: false });
    return () => element.removeEventListener('wheel', wheel);
  }, [expanded, svg]);
  const reset = () => { setZoom(Math.max(.1, Math.min(4, ((viewport.current?.clientWidth || 640) - 40) / naturalWidth))); viewport.current?.scrollTo(0, 0); };
  const viewer = () => <>
    <div className="diagram-toolbar" aria-label="Điều khiển sơ đồ">
      <div><button aria-label="Thu nhỏ sơ đồ" onClick={() => changeZoom(zoom - .25)} disabled={zoom <= .1}>−</button>
        <output aria-live="polite">{Math.round(zoom * 100)}%</output>
        <button aria-label="Phóng to sơ đồ" onClick={() => changeZoom(zoom + .25)} disabled={zoom >= 4}>+</button>
        <button onClick={reset}>Vừa khung</button></div>
      <button onClick={() => { setZoom(1); setExpanded(!expanded); }}>{expanded ? 'Đóng toàn màn hình' : 'Toàn màn hình ↗'}</button>
    </div>
    <div className="diagram-viewport" ref={viewport} tabIndex={0} aria-label="Sơ đồ: kéo để di chuyển, Ctrl hoặc Command và cuộn để phóng to"
      onPointerDown={(e) => { if (e.button !== 0) return; drag.current = { x: e.clientX, y: e.clientY, left: e.currentTarget.scrollLeft, top: e.currentTarget.scrollTop }; e.currentTarget.setPointerCapture(e.pointerId); }}
      onPointerMove={(e) => { if (!drag.current) return; e.currentTarget.scrollLeft = drag.current.left - (e.clientX - drag.current.x); e.currentTarget.scrollTop = drag.current.top - (e.clientY - drag.current.y); }}
      onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
      <div className="diagram-canvas" style={{ width: `${naturalWidth * zoom + 40}px` }} role="img" aria-label="Sơ đồ hệ thống" dangerouslySetInnerHTML={{ __html: svg }} />
    </div>
    <p className="diagram-hint">Kéo để di chuyển · Ctrl/⌘ + cuộn để phóng to</p>
  </>;
  return <figure className="docs-diagram">
    {svg ? expanded ? <p>Sơ đồ đang mở toàn màn hình.</p> : viewer() : <p>{failed ? 'Không render được sơ đồ. Xem mã bên dưới.' : 'Đang vẽ sơ đồ…'}</p>}
    <details><summary>Mã sơ đồ</summary><pre>{code}</pre></details>
    <dialog ref={dialog} className="diagram-dialog" aria-label="Sơ đồ toàn màn hình" onCancel={() => setExpanded(false)} onClose={() => setExpanded(false)}>
      {expanded && viewer()}
    </dialog>
  </figure>;
}
