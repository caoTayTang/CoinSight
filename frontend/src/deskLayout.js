export const DESK_LAYOUT_KEY = 'coinsight.desk.layout.v1';
export const clampDockWidth = (width) => Math.max(340, Math.min(620, Number(width) || 420));
// Older saves may also hold a floating mode and rect; only the docked width is kept.
export function readDeskLayout(storage) {
  try {
    const v=JSON.parse(storage.getItem(DESK_LAYOUT_KEY));
    if(!v||typeof v!=='object')return null;
    return {dockWidth:clampDockWidth(v.dockWidth)};
  } catch {return null;}
}
