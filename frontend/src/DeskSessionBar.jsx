import { useEffect, useState } from 'react';
import { api, utc } from './format.js';
import { modelOptionLabel } from './deskSession.js';

// Model picker, conversation history and long-term memory for the Desk. Paid or slower models are an explicit
// choice; "Auto" keeps the router's tiers (Groq keys first, Bedrock last).
export default function DeskSessionBar({ model, onModel, threadId, onOpenThread, onNewChat, busy }) {
  const [models, setModels] = useState([]);
  const [panel, setPanel] = useState(null);
  const [threads, setThreads] = useState([]);
  const [memories, setMemories] = useState([]);
  const [user, setUser] = useState(null);
  const [error, setError] = useState('');

  // Refreshed after each answer: questions left and paid-model access change as the user asks (app/usage.py).
  useEffect(() => {
    if (busy) return;
    api('/v1/agent/models').then(r => setModels(r.routes || [])).catch(() => setModels([]));
    api('/v1/me').then(setUser).catch(() => setUser(null));
  }, [busy]);

  async function open(next) {
    setError('');
    if (panel === next) { setPanel(null); return; }
    setPanel(next);
    try {
      if (next === 'history') setThreads((await api('/v1/agent/threads')).threads || []);
      if (next === 'memory') setMemories((await api('/v1/agent/memories')).memories || []);
    } catch (e) { setError(e.message); }
  }
  async function remove(kind, id) {
    try {
      await api(kind === 'thread' ? `/v1/agent/threads/${id}` : `/v1/agent/memories/${id}`, { method: 'DELETE' });
      if (kind === 'thread') { setThreads(t => t.filter(x => x.thread_id !== id)); if (id === threadId) onNewChat(); }
      else setMemories(m => m.filter(x => x.id !== id));
    } catch (e) { setError(e.message); }
  }

  return <div className="desk-session">
    <div className="desk-session-bar">
      <label className="desk-model"><span className="sr-only">Model</span>
        <select value={model} onChange={e => onModel(e.target.value)} disabled={busy} title="Which model answers">
          <option value="auto">Auto · router picks</option>
          {models.map(r => <option key={r.name} value={r.name} disabled={!r.available || r.allowed === false} title={r.reason}>{modelOptionLabel(r)}</option>)}
        </select>
      </label>
      <button type="button" onClick={onNewChat} disabled={busy}>New chat</button>
      <button type="button" aria-expanded={panel === 'history'} onClick={() => open('history')}>History</button>
      <button type="button" aria-expanded={panel === 'memory'} onClick={() => open('memory')}>Memory</button>
      {user?.usage && !user.usage.owner && <span className="desk-user" title={`Paid-model questions left today: ${user.usage.paid_left}`}>{user.usage.questions_left}/{user.usage.daily_limit} questions left today</span>}
      {user?.email && <span className="desk-user" title="Signed in with Cloudflare Access">{user.email}</span>}
    </div>
    {panel && <div className="desk-session-panel" role="region" aria-label={panel === 'history' ? 'Conversation history' : 'Saved memories'}>
      {error && <p className="response-warning">{error}</p>}
      {panel === 'history' && (threads.length ? <ul>{threads.map(t => <li key={t.thread_id} className={t.thread_id === threadId ? 'current' : ''}>
        <button type="button" onClick={() => { onOpenThread(t.thread_id); setPanel(null); }}><strong>{t.title || 'Untitled'}</strong><small>{utc(t.updated_at, true)} · {t.turns} turn{t.turns === 1 ? '' : 's'}</small></button>
        <button type="button" className="desk-delete" aria-label="Delete conversation" onClick={() => remove('thread', t.thread_id)}>×</button>
      </li>)}</ul> : <p>No saved conversations yet.</p>)}
      {panel === 'memory' && <>
        <p className="desk-session-note">Notes the agent keeps across conversations. It saves one only when you ask it to remember something or state a lasting preference.</p>
        {memories.length ? <ul>{memories.map(m => <li key={m.id}><span>{m.text}</span>
          <button type="button" className="desk-delete" aria-label="Forget this note" onClick={() => remove('memory', m.id)}>×</button></li>)}</ul>
          : <p>Nothing saved. Try “remember that I prefer answers in Vietnamese”.</p>}
      </>}
    </div>}
  </div>;
}
