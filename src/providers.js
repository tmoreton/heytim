// Provider registry for OpenAI-compatible chat APIs.
// Add a new provider by appending an entry below — pickProvider() routes by
// the optional `prefix` matched against the model name.

const requireKey = (envVar) => {
  const k = process.env[envVar];
  if (!k) {
    throw new Error(`${envVar} not set. Run \`/env set ${envVar}=...\``);
  }
  return k;
};

export const providers = {
  fireworks: {
    baseUrl: "https://api.fireworks.ai/inference/v1",
    headers: () => ({
      "Content-Type": "application/json",
      Authorization: `Bearer ${requireKey("FIREWORKS_API_KEY")}`,
    }),
  },
  openrouter: {
    baseUrl: "https://openrouter.ai/api/v1",
    prefix: "openrouter/",
    headers: () => ({
      "Content-Type": "application/json",
      Authorization: `Bearer ${requireKey("OPENROUTER_API_KEY")}`,
      "HTTP-Referer": "https://github.com/tmoreton/tim",
      "X-Title": "tim",
    }),
  },
};

// Default provider when no prefix matches.
const DEFAULT = providers.fireworks;

// Pick a provider from the model name. Returns { provider, model } with any
// provider prefix stripped from `model` so it can be sent upstream as-is.
export const pickProvider = (model = "") => {
  for (const cfg of Object.values(providers)) {
    if (cfg.prefix && model.startsWith(cfg.prefix)) {
      return { provider: cfg, model: model.slice(cfg.prefix.length) };
    }
  }
  return { provider: DEFAULT, model };
};
