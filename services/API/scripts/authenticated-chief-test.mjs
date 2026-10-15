#!/usr/bin/env node
import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const catalog = JSON.parse(readFileSync(new URL('../../../catalog/catalog.json', import.meta.url), 'utf8'));
const expectedChief = catalog.bots.find((bot) => bot.id === 'chief');
const active = new Set(['pending', 'running', 'waiting', 'needs_input', 'awaiting_approval', 'awaiting_device']);
const ensure = (condition, code) => {
  if (!condition) {
    const error = new Error(`Chief release smoke failed (${code}).`);
    error.smokeCode = code;
    throw error;
  }
};
const sameIDs = (actual, expected) => Array.isArray(actual) && actual.length === expected.length
  && new Set(actual).size === actual.length && expected.every((id) => actual.includes(id));

export async function runChiefSmoke({ apiUrl, idToken, fetcher = fetch,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)), timeoutMs = 240_000 } = {}) {
  ensure(typeof apiUrl === 'string' && apiUrl && typeof idToken === 'string' && idToken, 'configuration_missing');
  let base;
  try { base = new URL(apiUrl); } catch { ensure(false, 'configuration_invalid'); }
  ensure(['https:', 'http:'].includes(base.protocol) && !base.username && !base.password, 'configuration_invalid');
  ensure(Number.isSafeInteger(timeoutMs) && timeoutMs >= 1000 && timeoutMs <= 240_000, 'timeout_invalid');
  base = apiUrl.replace(/\/$/, '');
  const completed = [], initialIDs = new Set(), fixtureIDs = new Set(), prompts = new Set(), chiefTurnIDs = new Set();
  const fixtureName = `Chief Check ${randomUUID()}`;
  const initialTagline = 'Temporary Chief release verification.';
  const editedTagline = 'Chief create, edit, and routing verified.';
  const fixturePrompt = 'Reply with the exact marker requested by the user and no other text. Do not use tools.';
  const marker = `HEYTIM_CHIEF_ROUTE_${randomUUID().replaceAll('-', '')}`;
  const routedTask = `Reply exactly ${marker} and nothing else.`;
  let chiefID, creationStarted = false, primaryError, cleanupSucceeded = true;
  const api = async (method, path, body, stage) => {
    let response;
    try {
      response = await fetcher(`${base}${path}`, { method,
        headers: { authorization: `Bearer ${idToken}`, ...(body === undefined ? {} : { 'content-type': 'application/json' }) },
        body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(25_000) });
    } catch { ensure(false, `${stage}_transport`); }
    if (!(response.ok || method === 'DELETE' && response.status === 404)) {
      try { ensure(false, `${stage}_http`); } catch (error) { error.httpStatus = response.status; throw error; }
    }
    let value;
    try { value = await response.json(); } catch { ensure(false, `${stage}_response`); }
    return value;
  };
  const bootstrap = () => api('GET', '/bootstrap', undefined, 'bootstrap');
  const messages = async (botID) => {
    const result = await api('GET', `/bots/${encodeURIComponent(botID)}/messages`, undefined, 'messages');
    ensure(Array.isArray(result.messages), 'messages_invalid');
    return result.messages;
  };
  const waitFor = async (read, predicate, stage) => {
    const deadline = Date.now() + timeoutMs;
    do {
      const value = await read();
      if (predicate(value)) return value;
      await sleep(1500);
    } while (Date.now() < deadline);
    ensure(false, `${stage}_timeout`);
  };
  const waitForReply = (botID, turnID) => waitFor(async () =>
    (await messages(botID)).find((message) => message.id === `${turnID}-assistant`), (reply) => {
    if (reply && ['error', 'cancelled', 'needs_input', 'awaiting_approval', 'awaiting_device'].includes(reply.status)) {
      ensure(false, 'turn_did_not_complete');
    }
    return reply?.status === 'complete';
  }, 'turn');
  const chiefTurn = async (text) => {
    prompts.add(text);
    const turn = await api('POST', `/bots/${encodeURIComponent(chiefID)}/messages`, { text }, 'chief_turn');
    ensure(typeof turn.turnId === 'string' && turn.turnId, 'chief_turn_identity');
    chiefTurnIDs.add(turn.turnId);
    await waitForReply(chiefID, turn.turnId);
  };
  const discoverFixture = (value) => {
    ensure(Array.isArray(value.bots), 'bootstrap_invalid');
    const matches = value.bots.filter((bot) => bot.name === fixtureName && !initialIDs.has(bot.id));
    ensure(matches.every((bot) => bot.systemRole !== 'chief'
      && typeof bot.id === 'string' && bot.id !== chiefID), 'fixture_identity_invalid');
    for (const bot of matches) fixtureIDs.add(bot.id);
    if (value.bots.some((bot) => !initialIDs.has(bot.id) && bot.name !== fixtureName)) {
      cleanupSucceeded = false;
      ensure(false, 'unexpected_new_bot');
    }
    ensure(matches.length <= 1, 'fixture_duplicate');
    return matches[0];
  };
  const cancelTurn = async (botID, turnID) => {
    try {
      await api('POST', `/bots/${encodeURIComponent(botID)}/messages/${encodeURIComponent(turnID)}/cancel`, undefined, 'cancel');
    } catch {
      const latest = (await messages(botID)).find((message) => message.id === `${turnID}-assistant`);
      ensure(latest && !active.has(latest.status), 'cleanup_cancel_failed');
    }
  };
  try {
    const initial = await bootstrap();
    ensure(Array.isArray(initial.bots), 'bootstrap_invalid');
    const chiefs = initial.bots.filter((bot) => bot.systemRole === 'chief' && bot.templateId === 'chief');
    ensure(chiefs.length === 1, 'chief_missing');
    const chief = chiefs[0];
    chiefID = chief.id;
    ensure(chief.templateVersion === 9 && expectedChief.version === 9, 'chief_version');
    ensure(expectedChief.toolIds.length === 12 && sameIDs(chief.toolIds, expectedChief.toolIds), 'chief_tools');
    ensure(expectedChief.skillIds.length === 17 && sameIDs(chief.skillIds, expectedChief.skillIds), 'chief_skills');
    ensure(initial.constraints?.maxSkillsPerBot === 20, 'skill_limit');
    for (const bot of initial.bots) initialIDs.add(bot.id);
    completed.push('chief_defaults');
    const billing = await api('GET', '/billing', undefined, 'billing');
    ensure(Number.isSafeInteger(billing.creditsRemaining) && billing.creditsRemaining >= 4, 'insufficient_credits');
    completed.push('credit_preflight');
    ensure(!(await messages(chiefID)).some((message) => message.role === 'assistant' && active.has(message.status)), 'chief_busy');

    creationStarted = true;
    await chiefTurn(`Create exactly one temporary custom bot with this exact configuration: ${JSON.stringify({
      name: fixtureName, tagline: initialTagline, prompt: fixturePrompt, color: '#3984F6', toolIds: [], skillIds: [],
    })}. Use create_bot with tool_ids=[] and skill_ids=[]. Preserve all existing bots, including Chief. Apply the creation now and finish.`);
    const fixture = discoverFixture(await bootstrap());
    ensure(fixture && fixture.tagline === initialTagline && fixture.prompt === fixturePrompt && fixture.color === '#3984F6'
      && sameIDs(fixture.toolIds, []) && sameIDs(fixture.skillIds, []), 'chief_create_not_applied');
    completed.push('chief_create');

    await chiefTurn(`Update only the tagline of the existing bot with ID ${fixture.id} to exactly ${JSON.stringify(editedTagline)}. Use update_bot and preserve its name, prompt, color, tools, and skills. Apply the edit now and finish.`);
    const edited = discoverFixture(await bootstrap());
    ensure(edited?.id === fixture.id && edited.tagline === editedTagline && edited.prompt === fixturePrompt
      && edited.color === fixture.color && sameIDs(edited.toolIds, []) && sameIDs(edited.skillIds, []), 'chief_edit_not_applied');
    completed.push('chief_edit');

    await chiefTurn(`Route one task to the existing bot with ID ${fixture.id} using route_to_bot. Forward exactly this task text: ${JSON.stringify(routedTask)}. The teammate must answer in its own chat. Queue it once and finish without answering the task yourself.`);
    const routedMessages = await waitFor(() => messages(fixture.id), (items) =>
      items.some((message) => message.role === 'user' && message.source === 'bot_route'), 'routing');
    const handoffs = routedMessages.filter((message) => message.role === 'user' && message.source === 'bot_route');
    ensure(handoffs.length === 1 && handoffs[0].text === routedTask
      && handoffs[0].id?.endsWith('-user'), 'routing_identity');
    const child = await waitForReply(fixture.id, handoffs[0].id.slice(0, -'-user'.length));
    ensure(typeof child.text === 'string' && child.text.trim() === marker, 'routing_reply');
    ensure((await messages(fixture.id)).filter((message) => message.role === 'user' && message.source === 'bot_route').length === 1,
      'routing_duplicate');
    completed.push('chief_routing');
  } catch (error) {
    primaryError = error;
  } finally {
    if (creationStarted) {
      try {
        for (const message of await messages(chiefID)) {
          if (message.role === 'user' && prompts.has(message.text) && message.id?.endsWith('-user')) {
            chiefTurnIDs.add(message.id.slice(0, -'-user'.length));
          }
        }
        for (const turnID of chiefTurnIDs) {
          const reply = (await messages(chiefID)).find((message) => message.id === `${turnID}-assistant`);
          if (reply && active.has(reply.status)) await cancelTurn(chiefID, turnID);
        }
        discoverFixture(await bootstrap());
      } catch { cleanupSucceeded = false; }
      for (const botID of fixtureIDs) {
        try {
          for (const message of await messages(botID)) {
            if (message.role === 'assistant' && active.has(message.status) && message.id?.endsWith('-assistant')) {
              await cancelTurn(botID, message.id.slice(0, -'-assistant'.length));
            }
          }
          for (let attempt = 0; attempt < 4; attempt += 1) {
            try {
              await api('DELETE', `/bots/${encodeURIComponent(botID)}`, undefined, 'cleanup');
              break;
            } catch (error) {
              if (error.httpStatus !== 409 || attempt === 3) throw error;
              await sleep(500 * (attempt + 1));
            }
          }
        } catch { cleanupSucceeded = false; }
      }
    }
  }
  const summary = { passed: !primaryError && cleanupSucceeded, completed, cleanupSucceeded,
    chiefTurns: chiefTurnIDs.size, routedTurnsVerified: completed.includes('chief_routing') ? 1 : 0 };
  if (primaryError || !cleanupSucceeded) {
    const error = new Error('Chief release smoke failed.');
    error.smokeSummary = { ...summary, code: primaryError?.smokeCode ?? 'cleanup_failed' };
    throw error;
  }
  return summary;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    console.log(JSON.stringify(await runChiefSmoke({ apiUrl: process.env.HEYTIM_API_URL,
      idToken: process.env.HEYTIM_ID_TOKEN, timeoutMs: Number(process.env.HEYTIM_CHIEF_SMOKE_TIMEOUT_MS ?? 240_000) })));
  } catch (error) {
    console.error(JSON.stringify(error.smokeSummary ?? { passed: false, code: error.smokeCode ?? 'chief_smoke_failed' }));
    process.exitCode = 1;
  }
}
