// Minimal Fireworks (OpenAI-compatible) client. Uses native fetch + SSE parsing.

const BASE_URL = "https://api.fireworks.ai/inference/v1";

const getKey = () => {
  const k = process.env.FIREWORKS_API_KEY;
  if (!k) {
    console.error("Set FIREWORKS_API_KEY in your environment.");
    process.exit(1);
  }
  return k;
};

const headers = () => ({
  "Content-Type": "application/json",
  Authorization: `Bearer ${getKey()}`,
});

const throwIfBad = async (res) => {
  if (res.ok) return;
  const text = await res.text().catch(() => "");
  const err = new Error(`API ${res.status}: ${text.slice(0, 300)}`);
  err.status = res.status;
  throw err;
};

export async function complete(body, { signal } = {}) {
  const res = await fetch(`${BASE_URL}/chat/completions`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(body),
    signal,
  });
  await throwIfBad(res);
  return res.json();
}

export async function* stream(body, { signal } = {}) {
  const res = await fetch(`${BASE_URL}/chat/completions`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ ...body, stream: true }),
    signal,
  });
  await throwIfBad(res);

  const decoder = new TextDecoder();
  let buffer = "";

  for await (const chunk of res.body) {
    buffer += decoder.decode(chunk, { stream: true });
    // SSE events are separated by a blank line.
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";

    for (const evt of events) {
      for (const line of evt.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        const payload = line.slice(6).trim();
        if (payload === "[DONE]") return;
        try {
          yield JSON.parse(payload);
        } catch {
          // skip malformed chunk
        }
      }
    }
  }
}
