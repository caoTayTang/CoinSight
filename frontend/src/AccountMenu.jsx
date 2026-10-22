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

  if (me?.email) return <div className="account-menu">
    <span className="account-email" title={me.provider ? `Signed in with ${NAMES[me.provider] || me.provider}` : undefined}>{me.email}</span>
    {providers.length > 0 && me.provider !== 'cloudflare-access' &&
      <button type="button" className="button button-secondary" onClick={signOut}>Sign out</button>}
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
