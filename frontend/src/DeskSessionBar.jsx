import { useEffect, useState } from 'react';
import { api, utc } from './format.js';
import { modelOptionLabel } from './deskSession.js';

// Model picker, conversation history and long-term memory for the Desk. Paid or slower models are an explicit
// choice; "Auto" keeps the router's tiers (Groq keys first, Bedrock last).
const ICONS = {
  new: 'M11.5 2.5l2 2L7 11H5V9l6.5-6.5zM13 9v4a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h4',
  history: 'M8 14A6 6 0 1 0 2.4 6M2 2.5V6h3.5M8 5v3.2l2.2 1.4',
  memory: 'M4 2.5h8a.5.5 0 0 1 .5.5v10.5L8 11l-4.5 2.5V3a.5.5 0 0 1 .5-.5z',
};
const Icon = ({d}) => <svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5"
  strokeLinecap="round" strokeLinejoin="round"><path d={d}/></svg>;

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
  useEffect(() => {
    const reload = () => api('/v1/me').then(setUser).catch(() => setUser(null));
    window.addEventListener('coinsight-auth', reload);
    return () => window.removeEventListener('coinsight-auth', reload);
  }, []);

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
      <button type="button" className="session-icon" onClick={onNewChat} disabled={busy} aria-label="New chat" title="New chat"><Icon d={ICONS.new}/></button>
      <button type="button" className="session-icon" aria-expanded={panel === 'history'} onClick={() => open('history')} aria-label="History" title="History"><Icon d={ICONS.history}/></button>
      <button type="button" className="session-icon" aria-expanded={panel === 'memory'} onClick={() => open('memory')} aria-label="Memory" title="Memory: notes kept across chats"><Icon d={ICONS.memory}/></button>
      {user?.usage && !user.usage.owner && !user.usage.unavailable && <span className="desk-user" title={user.anonymous ? 'Free models only. Sign in for more questions and Claude Haiku.' : `Paid-model questions left today: ${user.usage.paid_left}`}>{user.usage.questions_left}/{user.usage.daily_limit} {user.anonymous ? 'free questions left · sign in for more' : 'questions left today'}</span>}
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
