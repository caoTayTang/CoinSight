const url = process.env.COIN_SIGHT_WS_URL || 'ws://localhost:3000/api/v1/assets/BTC/stream';
const socket = new WebSocket(url);
const timeout = setTimeout(() => {
  console.error('Timed out waiting for CoinSight live.snapshot');
  socket.close();
  process.exit(1);
}, 10000);

socket.addEventListener('message', (event) => {
  try {
    const payload = JSON.parse(event.data);
    if (payload.type !== 'live.snapshot' || payload.symbol !== 'BTC'
      || !payload.summary || !payload.metric) {
      throw new Error('Invalid live.snapshot envelope');
    }
    clearTimeout(timeout);
    console.log(`WebSocket snapshot: ${payload.symbol} · ${payload.summary.status} · ${payload.metric.status}`);
    socket.close();
    process.exit(0);
  } catch (error) {
    clearTimeout(timeout);
    console.error(error);
    socket.close();
    process.exit(1);
  }
});

socket.addEventListener('error', (error) => {
  clearTimeout(timeout);
  console.error('WebSocket connection failed', error);
  process.exit(1);
});
