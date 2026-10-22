import { useState } from 'react';
import { api } from './format.js';

const Thumb = ({ down }) => <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"
  style={down ? { transform: 'rotate(180deg)' } : undefined}>
  <path fill="currentColor" d="M2 21h4V9H2v12zm20-11a2 2 0 0 0-2-2h-6.3l1-4.6v-.3c0-.4-.2-.8-.4-1.1L13.2 1 6.6 7.6c-.4.4-.6.9-.6 1.4V19a2 2 0 0 0 2 2h9c.8 0 1.5-.5 1.8-1.2l3-7.1c.1-.2.2-.5.2-.7v-2z" />
</svg>;

// Thumbs up/down on one answer, stored with its run (PUT /v1/agent/runs/{id}/feedback). Owners read it in Admin.
export default function AnswerFeedback({ runId, initial }) {
  const [rating, setRating] = useState(initial ?? null);
  const [comment, setComment] = useState('');
  const [state, setState] = useState('idle');
  if (!runId) return null;

  async function send(value, text) {
    setState('saving');
    try {
      await api(`/v1/agent/runs/${runId}/feedback`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rating: value, ...(text ? { comment: text } : {}) }),
      });
      setRating(value);
      setState(text ? 'sent' : 'idle');
    } catch { setState('error'); }
  }

  return <div className="answer-feedback">
    <span>Was this useful?</span>
    <button type="button" aria-label="Useful" aria-pressed={rating === 1} disabled={state === 'saving'} onClick={() => send(1)}><Thumb /></button>
    <button type="button" aria-label="Not useful" aria-pressed={rating === -1} disabled={state === 'saving'} onClick={() => send(-1)}><Thumb down /></button>
    {rating === -1 && state !== 'sent' && <form onSubmit={(e) => { e.preventDefault(); if (comment.trim()) send(-1, comment.trim()); }}>
      <input value={comment} onChange={(e) => setComment(e.target.value)} maxLength={500} placeholder="What was wrong? (optional)" aria-label="What was wrong" />
      <button type="submit" disabled={!comment.trim() || state === 'saving'}>Send</button>
    </form>}
    {state === 'sent' && <small>Thanks, noted.</small>}
    {state === 'error' && <small className="negative">Not saved. Try again.</small>}
  </div>;
}
