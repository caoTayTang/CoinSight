export const THEME_KEY='coinsight.theme.v1';
export function applyTheme(theme) {
  const value=theme==='dark'?'dark':'light';
  document.documentElement.dataset.theme=value;
  document.documentElement.style.colorScheme=value;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content',value==='light'?'#f4f7fc':'#0b1019');
}
export function setTheme(theme) {
  applyTheme(theme);
  try { localStorage.setItem(THEME_KEY,document.documentElement.dataset.theme); } catch {}
  window.dispatchEvent(new Event('coinsight-theme-change'));
}
export function subscribeTheme(listener) {
  const storage=event=>{
    if(event.key!==THEME_KEY&&event.key!==null)return;
    applyTheme(event.newValue);listener();
  };
  window.addEventListener('coinsight-theme-change',listener);
  window.addEventListener('storage',storage);
  return()=>{window.removeEventListener('coinsight-theme-change',listener);window.removeEventListener('storage',storage);};
}
export const currentTheme=()=>document.documentElement.dataset.theme==='dark'?'dark':'light';
