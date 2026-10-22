import { useEffect, useRef, useState } from 'react';
import { signIn, signOut, supabase } from './auth.js';

const NAMES = { google: 'Google', github: 'GitHub' };

// A stable colour per email, for the initial when there's no profile picture.
function hue(text) {
  let h = 0;
  for (const c of text) h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
}

function Avatar({ email, picture }) {
  const [broken, setBroken] = useState(false);
  if (picture && !broken) {
    return <img className="account-avatar" src={picture} alt="" referrerPolicy="no-referrer" onError={() => setBroken(true)} />;
  }
  return <span className="account-avatar" style={{ background: `hsl(${hue(email)} 55% 45%)` }} aria-hidden="true">
    {email[0].toUpperCase()}</span>;
}

function usePopover() {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    const escape = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', escape); };
  }, [open]);
  return { open, setOpen, ref };
}

// Top-bar account: an avatar with a small menu when signed in, otherwise "Sign in" with the providers.
export default function AccountMenu({ me }) {
  const [providers, setProviders] = useState([]);
  const [picture, setPicture] = useState(null);
  const { open, setOpen, ref } = usePopover();
  useEffect(() => {
    const load = () => supabase().then(async (auth) => {
      setProviders(auth?.providers || []);
      const { data } = (await auth?.client.auth.getSession()) || {};
      setPicture(data?.session?.user?.user_metadata?.avatar_url || null);
    });
    load();
    window.addEventListener('coinsight-auth', load);
    return () => window.removeEventListener('coinsight-auth', load);
  }, []);

  // A Cloudflare Access identity can't be signed out from the page, so with Supabase it doesn't count here.
  const signedIn = me?.email && (!providers.length || providers.includes(me.provider));
  if (signedIn) return <div className="account-menu" ref={ref}>
    <button type="button" className="account-trigger" aria-label={`Account: ${me.email}`} aria-expanded={open}
      onClick={() => setOpen((v) => !v)}><Avatar email={me.email} picture={picture} /></button>
    {open && <div className="account-popover" role="menu">
      <strong className="account-email">{me.email}</strong>
      {NAMES[me.provider] && <small>Signed in with {NAMES[me.provider]}</small>}
      {providers.length > 0 && <button type="button" role="menuitem" className="button button-secondary" onClick={signOut}>Sign out</button>}
    </div>}
  </div>;
  if (!providers.length) return null;
  return <div className="account-menu" ref={ref}>
    <button type="button" className="button button-primary" aria-expanded={open} onClick={() => setOpen((v) => !v)}>Sign in</button>
    {open && <div className="account-popover" role="menu">
      <p>Sign in to ask more questions, keep your conversations and use Claude Haiku.</p>
      {providers.map((p) => <button key={p} type="button" role="menuitem" className="button button-secondary" onClick={() => signIn(p)}>
        Continue with {NAMES[p] || p}</button>)}
    </div>}
  </div>;
}
