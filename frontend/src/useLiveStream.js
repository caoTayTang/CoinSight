import { useEffect, useState } from 'react';

export function useLiveStream(symbol) {
  const [state, setState] = useState({ connection: 'connecting', summary: null, metric: null, now: Date.now() });

  useEffect(() => {
    const timer = window.setInterval(() => setState((current) => ({ ...current, now: Date.now() })), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!symbol) return undefined;
    let stopped = false;
    let socket;
    let retryTimer;
    let attempts = 0;
    setState({ connection: 'connecting', summary: null, metric: null, now: Date.now() });

    function connect() {
      if (stopped) return;
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      socket = new WebSocket(`${protocol}//${window.location.host}/api/v1/assets/${encodeURIComponent(symbol)}/stream`);
      socket.onopen = () => {
        attempts = 0;
        setState((current) => ({ ...current, connection: 'connected' }));
      };
      socket.onmessage = (event) => {
        let payload;
        try { payload = JSON.parse(event.data); } catch { return; }
        if (payload.symbol !== symbol) return;
        if (payload.type === 'live.snapshot') {
          setState({ connection: 'connected', summary: payload.summary, metric: payload.metric, now: Date.now() });
        } else if (payload.type === 'heartbeat') {
          setState((current) => ({ ...current, now: Date.now() }));
        }
      };
      socket.onclose = () => {
        if (stopped) return;
        setState((current) => ({ ...current, connection: 'reconnecting', now: Date.now() }));
        const delay = Math.min(1000 * 2 ** attempts, 15000);
        attempts += 1;
        retryTimer = window.setTimeout(connect, delay);
      };
      socket.onerror = () => socket.close();
    }

    connect();
    return () => {
      stopped = true;
      window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, [symbol]);

  return state;
}
