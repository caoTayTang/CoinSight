import {useEffect,useRef,useState} from 'react';
import {DESK_LAYOUT_KEY,clampDockWidth,readDeskLayout} from './deskLayout.js';
// The chat is always docked on the right; only its width changes (drag the left edge or use arrow keys).
export function useDeskLayout() {
  const [layout,setLayout]=useState(()=>readDeskLayout(window.localStorage)||{dockWidth:420});
  const panelRef=useRef(null),gesture=useRef(null);
  useEffect(()=>{
    document.documentElement.style.setProperty('--desk-width',`${layout.dockWidth}px`);
    try{localStorage.setItem(DESK_LAYOUT_KEY,JSON.stringify(layout));}catch{}
  },[layout]);
  function begin(event) {
    if(event.button!==0)return;
    event.preventDefault();
    gesture.current={x:event.clientX,dockWidth:layout.dockWidth};
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function move(event) {
    const g=gesture.current;if(!g)return;
    setLayout({dockWidth:clampDockWidth(Math.min(g.dockWidth-(event.clientX-g.x),innerWidth-300))});
  }
  const finish=()=>{gesture.current=null;};
  function keyboard(event) {
    const delta={ArrowLeft:-20,ArrowRight:20}[event.key];
    if(!delta)return;
    event.preventDefault();
    setLayout(v=>({dockWidth:clampDockWidth(v.dockWidth-delta)}));
  }
  return {layout,panelRef,begin,move,finish,keyboard};
}
