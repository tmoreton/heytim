#!/usr/bin/env node
import { pathToFileURL } from 'node:url';

const statuses = new Set(['pending', 'running', 'waiting', 'complete', 'error', 'cancelled',
  'needs_input', 'awaiting_approval', 'awaiting_device']);
const uuid = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
const routePrompt = new RegExp(`^Route one task to the existing bot with ID (ai-${uuid}) using route_to_bot\\. `
  + 'Forward exactly this task text: "(Reply exactly HEYTIM_CHIEF_ROUTE_[0-9a-f]{32} and nothing else\\.)"\\. '
  + 'The teammate must answer in its own chat\\. Queue it once and finish without answering the task yourself\\.$');
const identifier = (value) => typeof value === 'string' && /^[A-Za-z0-9_-]{1,80}$/.test(value);
const ensure = (condition, code) => {
  if (!condition) {
    const error = new Error('Chief routing diagnostics could not complete.');
    error.diagnosticCode = code;
    throw error;
  }
};
const status = (message) => message === undefined ? 'missing'
  : statuses.has(message.status) ? message.status : 'unknown';

// Classification never reproduces model text. Absence of a fixed tool activity label
// does not prove that no tool ran: normal progress may contain narration instead.
function classify(text) {
  if (typeof text !== 'string') return 'not_available';
  const value = text.slice(0, 64_000);
  if (value.includes('OpenRouter authentication is unavailable.')) return 'authentication_unavailable';
  if (value.includes('Bot not found or name is ambiguous; call list_bot_options first')) return 'routing_target_rejected';
  if (value.includes('Only one bot change can be made in a single message')) return 'mutation_limit_rejected';
  if (value.includes('Chief could not queue this task.')) return 'routing_dispatch_failed';
  if (value.includes('That teammate is already working.')) return 'teammate_busy';
  if (value.includes('I could not finish that request.')) return 'request_failed';
  if (/\bI (?:cannot|can't|won't|am unable to|will not)\b[^.!?\n]{0,80}\b(?:route|delegate|dispatch|queue|hand off)\b/i.test(value)) {
    return 'model_declined';
  }
  return 'none_recognized';
}

function syntheticRoute(message) {
  if (message?.role !== 'user' || typeof message.text !== 'string'
    || typeof message.id !== 'string' || !message.id.endsWith('-user') || message.id.length > 128) return undefined;
  const match = routePrompt.exec(message.text);
  if (!match || match[0] !== message.text) return undefined;
  const timestamp = typeof message.createdAt === 'string' ? Date.parse(message.createdAt) : NaN;
  if (!Number.isFinite(timestamp)) return undefined;
  return { targetID: match[1], task: match[2], turnID: message.id.slice(0, -'-user'.length), timestamp };
}

export async function runChiefRoutingDiagnostics({ apiUrl, idToken, fetcher = fetch } = {}) {
  ensure(typeof apiUrl === 'string' && apiUrl && apiUrl.length <= 2048
    && typeof idToken === 'string' && idToken, 'configuration_missing');
  let base;
  try { base = new URL(apiUrl); } catch { ensure(false, 'configuration_invalid'); }
  ensure(['https:', 'http:'].includes(base.protocol) && !base.username && !base.password
    && !base.search && !base.hash, 'configuration_invalid');
  base = base.href.replace(/\/$/, '');
  const get = async (path, stage, allowMissing = false) => {
    let response;
    try {
      response = await fetcher(`${base}${path}`, { method: 'GET',
        headers: { authorization: `Bearer ${idToken}` }, redirect: 'error', signal: AbortSignal.timeout(25_000) });
    } catch { ensure(false, `${stage}_transport`); }
    if (allowMissing && response.status === 404) return undefined;
    ensure(response.ok, `${stage}_http`);
    let result;
    try { result = await response.json(); } catch { ensure(false, `${stage}_response`); }
    ensure(result !== null && typeof result === 'object' && !Array.isArray(result), `${stage}_response`);
    return result;
  };
  const messages = async (botID, stage, allowMissing = false) => {
    const result = await get(`/bots/${encodeURIComponent(botID)}/messages`, stage, allowMissing);
    if (result === undefined) return undefined;
    ensure(Array.isArray(result.messages) && result.messages.length <= 1000, `${stage}_messages_invalid`);
    return result.messages;
  };
  const initial = await get('/bootstrap', 'bootstrap');
  ensure(Array.isArray(initial.bots) && initial.bots.length <= 1000, 'bootstrap_invalid');
  const chiefs = initial.bots.filter((bot) => bot?.systemRole === 'chief' && bot.templateId === 'chief');
  ensure(chiefs.length === 1 && identifier(chiefs[0].id), 'chief_identity_invalid');
  const chiefID = chiefs[0].id;
  const chiefMessages = await messages(chiefID, 'chief');
  const routes = chiefMessages.map(syntheticRoute).filter(Boolean).sort((a, b) => a.timestamp - b.timestamp);
  const latest = routes.at(-1);
  const summary = { diagnosticsCompleted: true, syntheticRouteFound: latest !== undefined,
    assistantStatus: 'missing', configurationChanged: false, routeToolActivityObserved: false,
    listBotOptionsActivityObserved: false, assistantTextClassification: 'not_available',
    targetListed: false, targetDeleted: false, targetHandoffState: 'not_checked', targetHandoffCount: 0,
    targetMatchingTaskCount: 0, targetHandoffAssistantStatus: 'missing' };
  if (!latest) return summary;
  ensure(latest.targetID !== chiefID, 'synthetic_target_invalid');
  const assistant = chiefMessages.find((message) => message?.role === 'assistant'
    && message.id === `${latest.turnID}-assistant`);
  const activity = Array.isArray(assistant?.activity) ? assistant.activity.slice(-12) : [];
  summary.assistantStatus = status(assistant);
  summary.configurationChanged = assistant?.configurationChanged === true;
  summary.routeToolActivityObserved = activity.includes('Using route to bot');
  summary.listBotOptionsActivityObserved = activity.includes('Using list bot options');
  summary.assistantTextClassification = classify(assistant?.text);
  // Listing absence is unavailable evidence, not proof of deletion or of a missing handoff.
  const targetExists = initial.bots.some((bot) => bot?.id === latest.targetID && bot.systemRole !== 'chief');
  summary.targetListed = targetExists;
  if (!targetExists) {
    summary.targetHandoffState = 'target_not_listed';
    return summary;
  }
  const targetMessages = await messages(latest.targetID, 'target', true);
  if (targetMessages === undefined) {
    summary.targetDeleted = true;
    summary.targetHandoffState = 'target_deleted';
    return summary;
  }
  const handoffs = targetMessages.filter((message) => message?.role === 'user' && message.source === 'bot_route');
  const matching = handoffs.filter((message) => message.text === latest.task);
  summary.targetHandoffCount = handoffs.length;
  summary.targetMatchingTaskCount = matching.length;
  summary.targetHandoffState = matching.length ? 'matching_handoff_observed'
    : handoffs.length ? 'different_handoff_observed' : 'no_handoff_observed';
  if (matching.length === 1 && typeof matching[0].id === 'string' && matching[0].id.endsWith('-user')) {
    const childID = `${matching[0].id.slice(0, -'-user'.length)}-assistant`;
    summary.targetHandoffAssistantStatus = status(targetMessages.find((message) =>
      message?.role === 'assistant' && message.id === childID));
  }
  return summary;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    console.log(JSON.stringify(await runChiefRoutingDiagnostics({
      apiUrl: process.env.HEYTIM_API_URL, idToken: process.env.HEYTIM_ID_TOKEN })));
  } catch (error) {
    console.error(JSON.stringify({ diagnosticsCompleted: false,
      code: error.diagnosticCode ?? 'diagnostics_failed' }));
    process.exitCode = 1;
  }
}
