// Web tools backed by Tavily: web_search (query the web) and web_fetch
// (extract clean content from a URL). Both use TAVILY_API_KEY.

const TAVILY_BASE = "https://api.tavily.com";
const MAX_OUTPUT = 30_000;

const getKey = () => {
  const k = process.env.TAVILY_API_KEY;
  if (!k) {
    throw new Error(
      "TAVILY_API_KEY not set. Run `/env set TAVILY_API_KEY=...`",
    );
  }
  return k;
};

const truncate = (s) =>
  s.length <= MAX_OUTPUT
    ? s
    : s.slice(0, MAX_OUTPUT) + `\n...[truncated ${s.length - MAX_OUTPUT} chars]`;

const post = async (path, body, signal) => {
  const res = await fetch(`${TAVILY_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getKey()}`,
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Tavily ${res.status}: ${text.slice(0, 300)}`);
  }
  return res.json();
};

export const webSearch = {
  schema: {
    type: "function",
    function: {
      name: "web_search",
      description:
        "Search the web via Tavily. Returns titles, URLs, and short content snippets. Use for current events, docs, references.",
      parameters: {
        type: "object",
        properties: {
          query: { type: "string" },
          max_results: {
            type: "number",
            description: "1-10, defaults to 5",
          },
          search_depth: {
            type: "string",
            enum: ["basic", "advanced"],
            description: "Defaults to basic. Use advanced for harder queries.",
          },
        },
        required: ["query"],
      },
    },
  },
  run: async ({ query, max_results = 5, search_depth = "basic" }, ctx = {}) => {
    try {
      const data = await post(
        "/search",
        { query, max_results, search_depth },
        ctx.signal,
      );
      const results = data.results || [];
      if (!results.length) return "(no results)";
      const lines = results.map(
        (r, i) => `${i + 1}. ${r.title}\n   ${r.url}\n   ${r.content || ""}`,
      );
      const answer = data.answer ? `Answer: ${data.answer}\n\n` : "";
      return truncate(answer + lines.join("\n\n"));
    } catch (e) {
      return `ERROR: ${e.message}`;
    }
  },
};

export const webFetch = {
  schema: {
    type: "function",
    function: {
      name: "web_fetch",
      description:
        "Fetch and extract the main content of one or more URLs as clean text via Tavily.",
      parameters: {
        type: "object",
        properties: {
          urls: {
            oneOf: [
              { type: "string" },
              { type: "array", items: { type: "string" } },
            ],
            description: "Single URL or array of URLs",
          },
        },
        required: ["urls"],
      },
    },
  },
  run: async ({ urls }, ctx = {}) => {
    const list = Array.isArray(urls) ? urls : [urls];
    try {
      const data = await post("/extract", { urls: list }, ctx.signal);
      const results = data.results || [];
      if (!results.length) return "(no content extracted)";
      const parts = results.map(
        (r) => `--- ${r.url} ---\n${r.raw_content || "(empty)"}`,
      );
      const failed = (data.failed_results || []).map(
        (f) => `--- ${f.url} (failed) ---\n${f.error || "unknown error"}`,
      );
      return truncate([...parts, ...failed].join("\n\n"));
    } catch (e) {
      return `ERROR: ${e.message}`;
    }
  },
};
