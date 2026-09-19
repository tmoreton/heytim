#!/usr/bin/env node

import { performance } from 'node:perf_hooks';

const options = new Map();
for (let index = 2; index < process.argv.length; index += 2) {
  const key = process.argv[index];
  const value = process.argv[index + 1];
  if (!key?.startsWith('--') || value === undefined) {
    throw new Error(`Expected --name value arguments; received ${key ?? 'nothing'}.`);
  }
  options.set(key.slice(2), value);
}

const apiUrl = process.env.HEYTIM_API_URL;
const accessToken = process.env.HEYTIM_ACCESS_TOKEN;
if (!apiUrl || !accessToken) {
  throw new Error('Set HEYTIM_API_URL and HEYTIM_ACCESS_TOKEN before running the load test.');
}

const positiveInteger = (name, fallback) => {
  const value = Number(options.get(name) ?? fallback);
  if (!Number.isInteger(value) || value <= 0) {
    throw new Error(`--${name} must be a positive integer.`);
  }
  return value;
};

const requestCount = positiveInteger('requests', 40);
const concurrency = positiveInteger('concurrency', 8);
const timeoutMs = positiveInteger('timeout-ms', 10_000);
const p99TargetMs = positiveInteger('p99-target-ms', 5_000);
const requestPath = options.get('path') ?? '/bootstrap';
if (!requestPath.startsWith('/')) {
  throw new Error('--path must begin with /.');
}

const target = new URL(requestPath, apiUrl.endsWith('/') ? apiUrl : `${apiUrl}/`);
const timings = [];
const statuses = new Map();
const failures = [];
let nextRequest = 0;

const runRequest = async (requestNumber) => {
  const startedAt = performance.now();
  try {
    const response = await fetch(target, {
      headers: { authorization: `Bearer ${accessToken}` },
      signal: AbortSignal.timeout(timeoutMs),
    });
    await response.arrayBuffer();
    const elapsedMs = performance.now() - startedAt;
    timings.push(elapsedMs);
    statuses.set(response.status, (statuses.get(response.status) ?? 0) + 1);
    if (!response.ok) {
      failures.push({ requestNumber, status: response.status });
    }
  } catch (error) {
    failures.push({
      requestNumber,
      error: error instanceof Error ? error.name : 'UnknownError',
    });
  }
};

const worker = async () => {
  while (nextRequest < requestCount) {
    const requestNumber = nextRequest;
    nextRequest += 1;
    await runRequest(requestNumber + 1);
  }
};

const startedAt = performance.now();
await Promise.all(
  Array.from({ length: Math.min(concurrency, requestCount) }, () => worker()),
);
const totalElapsedMs = performance.now() - startedAt;

timings.sort((left, right) => left - right);
const percentile = (fraction) => {
  if (timings.length === 0) return null;
  return timings[Math.max(0, Math.ceil(timings.length * fraction) - 1)];
};
const round = (value) => (value === null ? null : Math.round(value * 100) / 100);
const report = {
  target: target.toString(),
  requests: requestCount,
  concurrency,
  completed: timings.length,
  failures: failures.length,
  statuses: Object.fromEntries([...statuses.entries()].sort(([left], [right]) => left - right)),
  latencyMs: {
    p50: round(percentile(0.5)),
    p95: round(percentile(0.95)),
    p99: round(percentile(0.99)),
    max: round(timings.at(-1) ?? null),
  },
  totalElapsedMs: round(totalElapsedMs),
  p99TargetMs,
};

console.log(JSON.stringify(report, null, 2));
if (failures.length > 0 || report.latencyMs.p99 === null || report.latencyMs.p99 > p99TargetMs) {
  process.exitCode = 1;
}
