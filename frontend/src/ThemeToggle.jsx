import {useSyncExternalStore} from 'react';
import {currentTheme,setTheme,subscribeTheme} from './theme.js';
export default function ThemeToggle() {
  const theme=useSyncExternalStore(subscribeTheme,currentTheme,()=> 'light');
  const next=theme==='dark'?'light':'dark';
  return <button className="theme-toggle" type="button" aria-label={`Switch to ${next} mode`}
    title={`Switch to ${next} mode`} onClick={()=>setTheme(next)}>
    <span aria-hidden="true">{theme==='dark'?'☀':'☾'}</span><span>{next==='light'?'Light':'Dark'}</span>
  </button>;
}
