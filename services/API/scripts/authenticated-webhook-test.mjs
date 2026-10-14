#!/usr/bin/env node
// Deployed cloud transport smoke. Local decisions below are explicitly simulated;
// the real packaged Mac model is evaluated separately by packages/heytim-decider.
import { createHmac, randomUUID } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { assertBootstrapReady } from './bootstrap-release-contract.mjs';

const modelId = 'StrandsAgents/strands-decider-2B-qwen3.5-v1-2610';
const modelRevision = '216d1ccb46a9e9b036eb9187b248db98480f77d4';
const active = new Set(['pending', 'running', 'waiting', 'needs_input', 'awaiting_approval', 'awaiting_device']);
const ensure = (condition, message) => { if (!condition) throw new Error(message); };

export function genericDelivery(secret, value, timestamp = String(Math.floor(Date.now() / 1000))) {
  const body = JSON.stringify(value);
  return { body, headers: { 'content-type': 'application/json', 'x-webhook-timestamp': timestamp,
    'x-webhook-signature': `sha256=${createHmac('sha256', secret).update(`${timestamp}.${body}`).digest('hex')}` } };
}

export function pebbleTestDelivery(secret, deliveryId = randomUUID(), timestamp = String(Math.floor(Date.now() / 1000))) {
  const boundary = `smoke-${randomUUID()}`;
  const body = Buffer.concat([
    Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="transcription"\r\n\r\nSynthetic webhook test; do not run a bot.\r\n--${boundary}\r\nContent-Disposition: form-data; name="recordedAt"\r\n\r\n${Date.now()}\r\n--${boundary}\r\nContent-Disposition: form-data; name="client"\r\n\r\nring\r\n--${boundary}\r\nContent-Disposition: form-data; name="audio"; filename="smoke.m4a"\r\nContent-Type: audio/mp4\r\n\r\n`),
    Buffer.from([0, 255, 13, 10, 128]), Buffer.from(`\r\n--${boundary}--\r\n`),
  ]);
  const prefix = `v1\n${timestamp}\n${deliveryId}\ntest-event\n1\n`;
  return { body, headers: { 'content-type': `multipart/form-data; boundary=${boundary}`,
    'x-index-webhook-version': '1', 'x-index-timestamp': timestamp,
    'x-index-delivery': deliveryId, 'x-index-trigger': 'test-event', 'x-index-test': 'true',
    'x-index-signature': createHmac('sha256', secret).update(prefix).update(body).digest('hex') } };
}

export async function runWebhookSmoke({ apiUrl, idToken, fetcher = fetch,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)), timeoutMs = 100_000 } = {}) {
  ensure(typeof apiUrl === 'string' && apiUrl && typeof idToken === 'string' && idToken,
    'Set HEYTIM_API_URL and HEYTIM_ID_TOKEN before running the webhook smoke.');
  ensure(Number.isSafeInteger(timeoutMs) && timeoutMs >= 1000 && timeoutMs <= 240_000,
    'Webhook completion timeout must be between 1000 and 240000 milliseconds.');
  const base = apiUrl.replace(/\/$/, '');
  ensure(['https:', 'http:'].includes(new URL(base).protocol), 'The API URL must use HTTP or HTTPS.');
  const bots = [], sources = [], completed = [];
  const fixturePrefix = `WH ${randomUUID()}`;
  const plannedBotNames = new Set(), plannedSourceNames = new Set();
  const deviceId = randomUUID();
  let deviceRegistered = false, primaryError, cleanupSucceeded = true;
  const call = async (method, path, body, stage, { raw, headers = {}, expected } = {}) => {
    const attempts = ['GET', 'PUT', 'DELETE'].includes(method) || raw || path.endsWith('/result') ? 3 : 1;
    let response;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      try {
        response = await fetcher(`${base}${path}`, { method,
          headers: { ...(raw ? {} : { authorization: `Bearer ${idToken}` }),
            ...(body === undefined || raw ? {} : { 'content-type': 'application/json' }), ...headers },
          body: body === undefined ? undefined : raw ? body : JSON.stringify(body),
          signal: AbortSignal.timeout(25_000) });
      } catch {
        if (attempt + 1 === attempts) throw new Error(`${stage}: request failed or timed out.`);
      }
      if (response && ![429, 500, 502, 503, 504].includes(response.status)) break;
      if (attempt + 1 < attempts) await sleep(250 * (attempt + 1));
    }
    let value;
    try { value = await response.json(); } catch { value = {}; }
    if (expected) {
      ensure(expected.includes(response.status), `${stage}: unexpected HTTP status ${response.status}.`);
    } else {
      ensure(response.ok || method === 'DELETE' && response.status === 404, `${stage}: HTTP ${response.status}.`);
    }
    // Provider messages, transcripts, source URLs, credentials and tokens never enter diagnostics.
    return value;
  };
  const api = (method, path, body, stage = 'Authenticated API') => call(method, path, body, stage);
  const incoming = (source, delivery, stage, expected) => call('POST',
    `/public/webhooks/incoming/${encodeURIComponent(source.id)}`, delivery.body, stage,
    { raw: true, headers: delivery.headers, expected });
  const events = async () => (await api('GET', '/webhook-events', undefined, 'Read fixture inbox')).events ?? [];
  const messages = async (botId) => (await api('GET', `/bots/${encodeURIComponent(botId)}/messages`, undefined, 'Read fixture conversation')).messages ?? [];
  const waitFor = async (read, predicate, stage) => {
    const deadline = Date.now() + timeoutMs;
    do {
      const value = await read();
      if (predicate(value)) return value;
      await sleep(1500);
    } while (Date.now() < deadline);
    throw new Error(`${stage}: did not complete within the bounded timeout.`);
  };
  const waitForEvent = (eventId) => waitFor(async () => (await events()).find((event) => event.id === eventId),
    (event) => {
      if (event && ['needs_review', 'test'].includes(event.status)) throw new Error('Fixture event was not dispatched.');
      return event?.status === 'queued' && typeof event.turnId === 'string';
    }, 'Dispatch fixture event');
  const answer = async (botId, eventId, expectedMarker) => {
    const event = await waitForEvent(eventId);
    const reply = await waitFor(async () => (await messages(botId)).find((message) => message.id === `${event.turnId}-assistant`),
      (value) => {
        if (value && ['error', 'cancelled', 'needs_input', 'awaiting_approval', 'awaiting_device'].includes(value.status)) {
          throw new Error('Fixture answer ended without a completed response.');
        }
        return value?.status === 'complete';
      }, 'Persist fixture answer');
    ensure(typeof reply.text === 'string' && reply.text.includes(expectedMarker), 'The fixture answer was not persisted as requested.');
    const stored = await messages(botId);
    ensure(stored.filter((message) => message.role === 'user').length === 1
      && stored.filter((message) => message.role === 'assistant').length === 1,
    'A replay created an extra fixture conversation turn.');
    return { event, reply };
  };
  const createBot = async (label, reasoningEffort = 'low') => {
    const name = `${fixturePrefix} ${label}`;
    plannedBotNames.add(name);
    const bot = await api('POST', '/bots', { name,
      tagline: 'Disposable deployed webhook transport fixture.', color: '#3984F6',
      prompt: 'Answer with only the exact short marker explicitly requested. Do not use tools.',
      toolIds: [], skillIds: [], reasoningEffort, conversationMode: 'chat' }, 'Create disposable tool-free bot');
    ensure(typeof bot.id === 'string' && bot.id, 'The fixture bot has no ID.');
    bots.push(bot.id);
    ensure(bot.toolIds?.length === 0 && bot.skillIds?.length === 0, 'The smoke bot must have no tools or skills.');
    return bot;
  };
  const createSource = async (value) => {
    const name = `${fixturePrefix} ${value.name}`;
    plannedSourceNames.add(name);
    const response = await api('POST', '/webhook-sources', { ...value, name }, 'Create disposable webhook source');
    ensure(typeof response.source?.id === 'string', 'The fixture source has no ID.');
    sources.push(response.source.id);
    ensure(typeof response.credential === 'string' && response.credential.length > 20
      && typeof response.signingSecret === 'string' && response.signingSecret.length > 20,
    'One-time webhook credentials were not returned.');
    return response;
  };
  try {
    assertBootstrapReady(await api('GET', '/bootstrap', undefined, 'Verify synthetic account bootstrap'));
    const billing = await api('GET', '/billing', undefined, 'Check two-turn credit budget');
    ensure(Number.isSafeInteger(billing.creditsRemaining) && billing.creditsRemaining >= 2,
      'The webhook smoke requires at least two remaining credits; no fixture resources were created.');
    const fixedBot = await createBot('Fixed');
    const fixed = await createSource({ name: 'Disposable fixed nested JSON webhook smoke', kind: 'generic',
      allowedBotIds: [fixedBot.id], fallbackBotId: fixedBot.id, routingMode: 'fixed',
      authentication: 'hmac', enabled: true, textPath: 'event.message.text' });
    const fixedMarker = `webhook-fixed-${randomUUID()}`;
    const fixedDelivery = genericDelivery(fixed.signingSecret, { eventId: randomUUID(),
      event: { message: { text: `Reply with only this marker: ${fixedMarker}` } } });
    await incoming(fixed.source, { ...fixedDelivery, body: `${fixedDelivery.body} ` }, 'Reject tampered generic signature', [401]);
    const accepted = await incoming(fixed.source, fixedDelivery, 'Accept fixed nested signed event', [202]);
    const duplicate = await incoming(fixed.source, fixedDelivery, 'Replay fixed signed event', [202]);
    ensure(accepted.eventId === duplicate.eventId, 'Replaying a delivery changed its event identity.');
    await answer(fixedBot.id, accepted.eventId, fixedMarker);
    await incoming(fixed.source, fixedDelivery, 'Replay completed fixed event', [202]);
    ensure((await messages(fixedBot.id)).filter((message) => message.role === 'user').length === 1,
      'A completed delivery replay duplicated its conversation turn.');
    completed.push('signed nested JSON reaches one completed persisted bot turn');

    const pebble = await createSource({ name: 'Disposable Pebble webhook signature smoke', kind: 'pebble',
      allowedBotIds: [fixedBot.id], routingMode: 'local', enabled: true });
    const pebbleDelivery = pebbleTestDelivery(pebble.signingSecret);
    const testEvent = await incoming(pebble.source, pebbleDelivery, 'Verify exact signed binary multipart test', [202]);
    ensure(testEvent.status === 'test', 'A Pebble test event must not run a bot.');
    await api('PUT', `/webhook-sources/${pebble.source.id}`, { enabled: false }, 'Disable fixture source');
    await incoming(pebble.source, pebbleDelivery, 'Disabled source rejects delivery', [401, 404, 409]);
    await api('PUT', `/webhook-sources/${pebble.source.id}`, { enabled: true }, 'Re-enable fixture source');
    const rotated = await api('POST', `/webhook-sources/${pebble.source.id}/rotate`, undefined, 'Rotate fixture credentials');
    const legacyHeaders = { 'content-type': pebbleDelivery.headers['content-type'], 'x-index-test': 'true' };
    await incoming(pebble.source, { body: pebbleDelivery.body,
      headers: { ...legacyHeaders, authorization: `Bearer ${pebble.credential}` } }, 'Reject retired bearer credential', [401]);
    await incoming(pebble.source, pebbleDelivery, 'Reject retired signing secret', [401]);
    const currentLegacy = await incoming(pebble.source, { body: pebbleDelivery.body,
      headers: { ...legacyHeaders, authorization: `Bearer ${rotated.credential}` } }, 'Accept rotated legacy test credential', [202]);
    ensure(currentLegacy.status === 'test', 'A rotated test delivery must not run a bot.');
    const currentSigned = await incoming(pebble.source, pebbleTestDelivery(rotated.signingSecret), 'Accept rotated signed test delivery', [202]);
    ensure(currentSigned.status === 'test', 'A rotated signed test must not run a bot.');
    ensure((await messages(fixedBot.id)).filter((message) => message.role === 'user').length === 1,
      'A test or rejected credential delivery unexpectedly created a turn.');
    completed.push('Pebble test suppression, source disable and credential rotation');

    const localBot = await createBot('Local', 'high');
    const local = await createSource({ name: 'Disposable local routing transport smoke', kind: 'generic',
      allowedBotIds: [localBot.id], routingMode: 'local', enabled: true, authentication: 'hmac' });
    const localMarker = `webhook-local-${randomUUID()}`;
    const localDelivery = genericDelivery(local.signingSecret, { eventId: randomUUID(), text: `Reply with only this marker: ${localMarker}` });
    const localEvent = await incoming(local.source, localDelivery, 'Accept local routing fixture', [202]);
    ensure(localEvent.status === 'awaiting_routing', 'Local delivery did not wait for a Mac routing decision.');
    ensure((await messages(localBot.id)).length === 0, 'Local ingress invoked a bot before a routing decision.');
    deviceRegistered = true;
    await api('PUT', `/devices/${deviceId}/routing`, { schemaVersion: 1, appVersion: 'deployed-smoke-simulated-mac', modelId, modelRevision }, 'Register simulated Mac transport');
    const claim = await waitFor(async () => (await api('GET', `/devices/${deviceId}/routing-requests`, undefined, 'Claim simulated routing fixture')).requests?.[0],
      (value) => {
        if (value && value.id !== localEvent.eventId) throw new Error('The synthetic account has an unrelated pending routing request.');
        return Boolean(value);
      }, 'Lease local routing fixture');
    ensure(claim.modelId === modelId && claim.modelRevision === modelRevision
      && claim.bots?.length === 1 && claim.bots[0].id === localBot.id,
    'The routing lease did not preserve its model or source bot allowlist.');
    // This verifies deployed transport only. No claim of model inference is made.
    const simulatedResult = { requestDigest: claim.requestDigest, leaseToken: claim.leaseToken,
      modelId, modelRevision, botId: localBot.id, confidence: .99,
      probabilities: { [localBot.id]: .995, clarify: .005 }, reasoningEffort: 'low',
      reasoningConfidence: .95, reasoningDeferred: false, suggestedReasoningEffort: 'low' };
    const resultPath = `/devices/${deviceId}/routing-requests/${claim.id}/result`;
    await api('POST', resultPath, simulatedResult, 'Submit explicitly simulated Mac result');
    const persisted = await answer(localBot.id, localEvent.eventId, localMarker);
    ensure(persisted.event.routingDecision?.method === 'local'
      && persisted.event.routingDecision?.reasoningEffort === 'low'
      && persisted.reply.usageSummary?.reasoningEffort === 'low',
    'The per-turn routing and reasoning decision was not preserved.');
    const savedLocalBot = (await api('GET', '/bootstrap', undefined, 'Check saved bot preference')).bots.find((bot) => bot.id === localBot.id);
    ensure(savedLocalBot?.reasoningEffort === 'high', 'Per-turn routing changed the saved bot reasoning preference.');
    await api('POST', resultPath, simulatedResult, 'Replay simulated Mac result');
    await incoming(local.source, localDelivery, 'Replay completed local source delivery', [202]);
    ensure((await messages(localBot.id)).filter((message) => message.role === 'user').length === 1,
      'Replayed local results created another turn.');
    completed.push('simulated Mac lease/result reaches one completed persisted bot turn');
  } catch (error) {
    primaryError = error;
  } finally {
    // POST creates are never retried. Recover only this run's exact random names
    // if a successful create lost its HTTP response before returning its ID.
    if (plannedBotNames.size || plannedSourceNames.size) {
      try {
        const bootstrap = await api('GET', '/bootstrap', undefined, 'Discover disposable bots for cleanup');
        for (const bot of bootstrap.bots ?? []) {
          if (plannedBotNames.has(bot.name) && !bots.includes(bot.id)) bots.push(bot.id);
        }
        const listed = await api('GET', '/webhook-sources', undefined, 'Discover disposable sources for cleanup');
        for (const source of listed.sources ?? []) {
          if (plannedSourceNames.has(source.name) && !sources.includes(source.id)) sources.push(source.id);
        }
      } catch { cleanupSucceeded = false; }
    }
    if (deviceRegistered) {
      try { await api('DELETE', `/devices/${deviceId}/routing`, undefined, 'Clean simulated Mac registration'); }
      catch { cleanupSucceeded = false; }
    }
    for (const sourceId of sources.reverse()) {
      try { await api('DELETE', `/webhook-sources/${sourceId}`, undefined, 'Clean disposable source'); }
      catch { cleanupSucceeded = false; }
    }
    for (const botId of bots.reverse()) {
      try {
        for (const message of await messages(botId)) {
          if (message.role === 'assistant' && active.has(message.status) && message.id.endsWith('-assistant')) {
            const turnId = message.id.slice(0, -'-assistant'.length);
            await api('POST', `/bots/${botId}/messages/${turnId}/cancel`, undefined, 'Cancel disposable in-flight turn');
          }
        }
        await api('DELETE', `/bots/${botId}`, undefined, 'Clean disposable bot');
      } catch { cleanupSucceeded = false; }
    }
  }
  if (primaryError) {
    const failure = new Error(primaryError instanceof Error ? primaryError.message : 'Webhook smoke failed.');
    failure.smokeSummary = { passed: false, completed, cleanupSucceeded };
    throw failure;
  }
  ensure(cleanupSucceeded, 'Disposable webhook smoke resources could not all be cleaned up.');
  return { passed: true, completed, cleanupSucceeded, modelTurns: 2,
    localDecisionEvidence: 'simulated cloud transport; real Mac inference evaluated separately',
    notificationEvidence: 'notification queue state is not exposed by the public API',
    physicalAPNsDeliveryVerified: false };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    console.log(JSON.stringify(await runWebhookSmoke({ apiUrl: process.env.HEYTIM_API_URL,
      idToken: process.env.HEYTIM_ID_TOKEN,
      timeoutMs: Number(process.env.HEYTIM_WEBHOOK_SMOKE_TIMEOUT_MS ?? 100_000) }), null, 2));
  } catch (error) {
    console.error(JSON.stringify(error.smokeSummary ?? { passed: false }));
    console.error(error instanceof Error ? error.message : 'Webhook smoke failed.');
    process.exitCode = 1;
  }
}
