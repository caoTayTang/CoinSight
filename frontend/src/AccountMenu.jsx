import { useEffect, useRef, useState } from 'react';
import { signIn, signOut, supabase } from './auth.js';

const NAMES = { google: 'Google', github: 'GitHub' };

// Top-bar sign-in: "Sign in" with the configured providers, or the signed-in email and "Sign out".
export default function AccountMenu({ me }) {
  const [providers, setProviders] = useState([]);
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => { supabase().then((auth) => setProviders(auth?.providers || [])); }, []);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  if (!providers.length) {
    // No Supabase: show who Cloudflare Access (or local development) says this is, if anyone.
    return me?.email ? <div className="account-menu"><span className="account-email">{me.email}</span></div> : null;
  }
  // A Cloudflare Access identity doesn't count as signed in here: it can't be signed out from the page.
  if (me?.email && providers.includes(me.provider)) return <div className="account-menu">
    <span className="account-email" title={`Signed in with ${NAMES[me.provider] || me.provider}`}>{me.email}</span>
    <button type="button" className="button button-secondary" onClick={signOut}>Sign out</button>
  </div>;
  return <div className="account-menu" ref={ref}>
    <button type="button" className="button button-primary" aria-expanded={open} onClick={() => setOpen((v) => !v)}>Sign in</button>
    {open && <div className="account-popover" role="menu">
      <p>Sign in to ask more questions, keep your conversations and use Claude Haiku.</p>
      {providers.map((p) => <button key={p} type="button" role="menuitem" className="button button-secondary" onClick={() => signIn(p)}>
        Continue with {NAMES[p] || p}</button>)}
    </div>}
  </div>;
}
