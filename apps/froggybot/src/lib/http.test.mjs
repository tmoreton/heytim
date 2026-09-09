import assert from 'node:assert/strict';
import test from 'node:test';

import {
  fetchWithTimeout,
  readableRequestError,
  RequestTimeoutError,
} from './http.ts';

const abortableFetch = (_input, init) => new Promise((_resolve, reject) => {
  init.signal.addEventListener('abort', () => {
    const error = new Error('aborted');
    error.name = 'AbortError';
    reject(error);
  }, { once: true });
});

test('aborts a hung request at its deadline', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = abortableFetch;
  try {
    await assert.rejects(fetchWithTimeout('https://example.com', {}, 5), RequestTimeoutError);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('preserves caller cancellation instead of reporting a timeout', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = abortableFetch;
  const controller = new AbortController();
  try {
    const request = fetchWithTimeout('https://example.com', { signal: controller.signal }, 1_000);
    controller.abort();
    await assert.rejects(request, (error) => error.name === 'AbortError');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('turns fetch transport failures into a useful connection error', () => {
  const error = readableRequestError(new TypeError('Network request failed'), 'fallback');
  assert.equal(error.message, 'Could not reach FroggyBot. Check your connection and try again.');
});
