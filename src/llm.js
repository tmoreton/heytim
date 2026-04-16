// LLM client (OpenAI-compatible API). Provider is picked from the model name
// via providers.js — see that file to add a new backend.
// complete() for single-shot, stream() for SSE streaming with retry logic.

import { pickProvider } from "./providers.js";

const resolveRequest = (body) => {
  const { provider, model } = pickProvider(body.model);
  return {
    url: `${provider.baseUrl}/chat/completions`,
    headers: provider.headers(),
    body: { ...body, model },
  };
};

const throwIfBad = async (res) => {
  if (res.ok) return;
  const text = await res.text().catch(() => "");
  const err = new Error(`API ${res.status}: ${text.slice(0, 300)}`);
  err.status = res.status;
  err.retryAfter = Number(res.headers.get("retry-after")) || 0;
  throw err;
};

const RETRY_STATUS = new Set([429, 500, 502, 503, 504]);
const MAX_ATTEMPTS = 5;
const ESC = "\x1b[";

// Clear current line and move to start (for cleaning up spinner before writing)
const clearLine = () => process.stdout.write(`\r${ESC}K`);

const fetchWithRetry = async (url, init) => {
  for (let attempt = 0; ; attempt++) {
    try {
      const res = await fetch(url, init);
      if (res.ok || !RETRY_STATUS.has(res.status) || attempt >= MAX_ATTEMPTS - 1) return res;
      const retryAfter = Number(res.headers.get("retry-after")) || 0;
      const wait = retryAfter * 1000 || backoff(attempt);
      clearLine();
      process.stderr.write(`  retrying in ${Math.round(wait)}ms (HTTP ${res.status}, attempt ${attempt + 2}/${MAX_ATTEMPTS})`);
      await sleep(wait, init.signal);
      clearLine();
    } catch (e) {
      if (init.signal?.aborted || attempt >= MAX_ATTEMPTS - 1) {
        if (e?.cause?.code) e.message = `${e.message} (${e.cause.code})`;
        throw e;
      }
      const wait = backoff(attempt);
      clearLine();
      process.stderr.write(`  retrying in ${Math.round(wait)}ms (${e.cause?.code || e.message}, attempt ${attempt + 2}/${MAX_ATTEMPTS})`);
      await sleep(wait, init.signal);
      clearLine();
    }
  }
};

const backoff = (attempt) => 250 * 2 ** attempt + Math.floor(Math.random() * 250);

const sleep = (ms, signal) =>
  new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(signal.reason);
    const t = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(t);
      reject(signal.reason);
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });

export async function complete(body, { signal } = {}) {
  const p = resolveRequest(body);
  const res = await fetchWithRetry(p.url, {
    method: "POST",
    headers: p.headers,
    body: JSON.stringify(p.body),
    signal,
  });
  await throwIfBad(res);
  return res.json();
}

export async function* stream(body, { signal } = {}) {
  const p = resolveRequest({ ...body, stream: true });
  const res = await fetchWithRetry(p.url, {
    method: "POST",
    headers: p.headers,
    body: JSON.stringify(p.body),
    signal,
  });
  await throwIfBad(res);

  const decoder = new TextDecoder();
  let buffer = "";
  let lineBuffer = "";

  for await (const chunk of res.body) {
    buffer += decoder.decode(chunk, { stream: true });
    
    // Process line by line to handle events split across chunks
    const lines = buffer.split("\n");
    // Keep the last (potentially incomplete) line in buffer
    buffer = lines.pop() ?? "";
    
    for (const line of lines) {
      lineBuffer += line;
      
      // Empty line means end of SSE event
      if (line === "") {
        // Parse the accumulated event data
        const dataMatch = lineBuffer.match(/data: (.+)/);
        if (dataMatch) {
          const payload = dataMatch[1].trim();
          if (payload === "[DONE]") return;
          try {
            yield JSON.parse(payload);
          } catch {
            // skip malformed chunk
          }
        }
        lineBuffer = "";
      } else {
        lineBuffer += "\n";
      }
    }
  }
  
  // Process any remaining data
  if (buffer) {
    lineBuffer += buffer;
    const dataMatch = lineBuffer.match(/data: (.+)/);
    if (dataMatch) {
      const payload = dataMatch[1].trim();
      if (payload !== "[DONE]") {
        try {
          yield JSON.parse(payload);
        } catch {
          // skip malformed chunk
        }
      }
    }
  }
}
