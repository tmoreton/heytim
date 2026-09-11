const MAX_POLL_DELAY_MS = 30_000;

export function nextPollingDelay(
  baseDelayMs: number,
  consecutiveFailures: number,
  random: () => number = Math.random,
): number {
  if (consecutiveFailures <= 0) return baseDelayMs;
  const bounded = Math.min(MAX_POLL_DELAY_MS, baseDelayMs * (2 ** consecutiveFailures));
  const jitter = 0.8 + Math.max(0, Math.min(1, random())) * 0.4;
  return Math.min(MAX_POLL_DELAY_MS, Math.round(bounded * jitter));
}
