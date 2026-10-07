// Presentation rules for observed data; these are not predictive signals.
export function liveReadiness(live) {
  const summary = live.summary;
  if (!summary?.data) return { status: 'unavailable', reason: 'No recent minute candles are available.' };
  if (live.connection !== 'connected') return { status: 'disconnected', reason: 'Connection interrupted. These are the last received observations.' };
  const observed = Date.parse(summary.provenance?.observed_at);
  const seconds = (live.now - observed) / 1000;
  if (!Number.isFinite(seconds) || seconds < -60 || seconds > 180 || summary.status === 'stale')
    return { status: 'stale', reason: 'The latest observation is old or its timestamp cannot be verified.' };
  const { observed_minutes: count, expected_minutes: expected } = summary.data;
  if (!Number.isFinite(count) || !Number.isFinite(expected) || expected <= 0 || count !== expected)
    return { status: 'insufficient_data', reason: 'The recent window is incomplete. Changes may not represent the full 15 minutes.' };
  if (summary.status !== 'ready') return { status: summary.status || 'unavailable', reason: 'The source has not marked this data ready.' };
  return { status: 'ready', reason: 'Recent candles cover the expected window. This describes past movement, not future direction.' };
}

export function predictionReadiness(prediction, now) {
  if (!prediction?.data) return false;
  const probability = prediction.data.probability_up;
  return prediction.status === 'ready' && typeof probability === 'number' && probability >= 0 && probability <= 1
    && prediction.data.target_date === new Date(now).toISOString().slice(0, 10);
}
