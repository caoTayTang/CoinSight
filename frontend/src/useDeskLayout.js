import {useEffect,useRef,useState} from 'react';
import {DESK_LAYOUT_KEY,fitDesk,readDeskLayout} from './deskLayout.js';
const viewport=()=>({width:window.innerWidth,height:window.innerHeight});
export function useDeskLayout() {
  const [layout,setLayout]=useState(()=>{
    const saved=readDeskLayout(window.localStorage);
    return saved?{...saved,rect:fitDesk(saved.rect,viewport())}:{mode:'docked',dockWidth:420,rect:fitDesk({x:innerWidth-500,y:110,width:470,height:660},viewport())};
  });
  const panelRef=useRef(null),gesture=useRef(null);
  useEffect(()=>{
    document.documentElement.style.setProperty('--desk-width',`${layout.dockWidth}px`);
    try{localStorage.setItem(DESK_LAYOUT_KEY,JSON.stringify(layout));}catch{}
  },[layout]);
  useEffect(()=>{
    const resize=()=>setLayout(v=>({...v,rect:fitDesk(v.rect,viewport())}));
    window.addEventListener('resize',resize);return()=>window.removeEventListener('resize',resize);
  },[]);
  function begin(event,kind) {
    if(event.button!==0)return;
    if(kind==='move'&&event.target.closest('button,a,input,textarea'))return;
    event.preventDefault();
    const r=panelRef.current.getBoundingClientRect();
    const rect={x:r.x,y:r.y,width:r.width,height:r.height};
    gesture.current={kind,x:event.clientX,y:event.clientY,rect,dockWidth:layout.dockWidth};
    event.currentTarget.setPointerCapture(event.pointerId);
    if(kind==='move')setLayout(v=>({...v,mode:'floating',rect:fitDesk(rect,viewport())}));
  }
  function move(event) {
    const g=gesture.current;if(!g)return;
    const dx=event.clientX-g.x,dy=event.clientY-g.y;
    setLayout(v=>g.kind==='dock-size'?{...v,dockWidth:Math.max(340,Math.min(620,innerWidth-300,g.dockWidth-dx))}:
      {...v,mode:'floating',rect:fitDesk(g.kind==='move'?{...g.rect,x:g.rect.x+dx,y:g.rect.y+dy}:
        {...g.rect,width:g.rect.width+dx,height:g.rect.height+dy},viewport())});
  }
  const finish=()=>{gesture.current=null;};
  const float=()=>setLayout(v=>({...v,mode:'floating',rect:fitDesk(v.rect,viewport())}));
  const dock=()=>setLayout(v=>({...v,mode:'docked'}));
  function keyboard(event,kind) {
    const delta={ArrowLeft:[-20,0],ArrowRight:[20,0],ArrowUp:[0,-20],ArrowDown:[0,20]}[event.key];
    if(!delta)return;
    event.preventDefault();
    setLayout(v=>kind==='dock-size'?{...v,dockWidth:Math.max(340,Math.min(620,v.dockWidth-delta[0]))}:
      {...v,mode:'floating',rect:fitDesk(kind==='move'?{...v.rect,x:v.rect.x+delta[0],y:v.rect.y+delta[1]}:
        {...v.rect,width:v.rect.width+delta[0],height:v.rect.height+delta[1]},viewport())});
  }
  return {layout,panelRef,begin,move,finish,float,dock,keyboard};
}
