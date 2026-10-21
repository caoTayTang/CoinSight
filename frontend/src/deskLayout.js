export const DESK_LAYOUT_KEY = 'coinsight.desk.layout.v1';
export function fitDesk(rect, viewport) {
  const width=Math.min(Math.max(Number(rect.width)||460,Math.min(340,viewport.width-16)),viewport.width-16);
  const height=Math.min(Math.max(Number(rect.height)||620,Math.min(380,viewport.height-16)),viewport.height-16);
  return {width,height,x:Math.max(8,Math.min(Number(rect.x)||8,viewport.width-width-8)),
    y:Math.max(8,Math.min(Number(rect.y)||8,viewport.height-height-8))};
}
export function readDeskLayout(storage) {
  try {
    const v=JSON.parse(storage.getItem(DESK_LAYOUT_KEY));
    if(!v||!['docked','floating'].includes(v.mode))return null;
    if(!['x','y','width','height'].every(k=>typeof v.rect?.[k]==='number'&&Number.isFinite(v.rect[k])))return null;
    return {mode:v.mode,rect:v.rect,dockWidth:Math.max(340,Math.min(620,Number(v.dockWidth)||420))};
  } catch {return null;}
}
