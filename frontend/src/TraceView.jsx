import {useEffect, useState} from 'react';
import ResponseCharts from './ResponseCharts.jsx';
import {api} from './format.js';

// Owners only: whether the signed-in user is an owner (from /v1/me), refreshed on sign-in and sign-out.
export function useOwner() {
  const [owner, setOwner] = useState(false);
  useEffect(() => {
    const load = () => api('/v1/me').then(me => setOwner(Boolean(me?.usage?.owner))).catch(() => setOwner(false));
    load();
    window.addEventListener('coinsight-auth', load);
    return () => window.removeEventListener('coinsight-auth', load);
  }, []);
  return owner;
}

// Jaeger stays on the home network; the API fetches the trace's span metadata for owners and it is drawn here.
export default function TraceView({traceId}) {
  const [state, setState] = useState(null);
  if (!/^[a-f0-9]{32}$/.test(traceId || '')) return null;
  const load = () => {
    setState({loading: true});
    api(`/v1/admin/traces/${traceId}`).then(result => setState({result})).catch(error => setState({error: error.message}));
  };
  return <div className="trace-view">
    {!state && <button type="button" onClick={load}>Show request trace</button>}
    {state?.loading && <small>Loading trace…</small>}
    {state?.error && <small className="response-warning">Trace unavailable: {state.error}</small>}
    {state?.result && (state.result.status === 'available'
      ? <ResponseCharts meta={{evidence: [{tool: 'inspect_trace', result: state.result}]}}/>
      : <small>{state.result.reason || 'No spans found for this trace.'}</small>)}
  </div>;
}
