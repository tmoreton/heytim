import assert from 'node:assert/strict';
import { createHmac, randomUUID } from 'node:crypto';
import { test } from 'node:test';
import { genericDelivery, pebbleTestDelivery, runWebhookSmoke } from './authenticated-webhook-test.mjs';

function mockCloud({ credits = 10, failLocalSubmission = false, loseCreatedSourceResponse = false,
  failCleanupBootstrap = false, cancelRace } = {}) {
  const state = { bots: new Map(), sources: new Map(), events: new Map(), deliveries: new Map(),
    conversations: new Map(), devices: new Set(), turns: 0, calls: [] };
  const response = (value, status = 200) => new Response(JSON.stringify(value), { status,
    headers: { 'content-type': 'application/json' } });
  const execute = (event, botId, effort) => {
    if (event.turnId) return;
    state.turns += 1;
    event.status = 'queued'; event.botId = botId; event.turnId = randomUUID();
    const marker = event.text.match(/marker: ([^\s]+)/)?.[1] ?? 'unexpected';
    state.conversations.set(botId, [
      { id: `${event.turnId}-user`, role: 'user', text: event.text, status: 'complete' },
      { id: `${event.turnId}-assistant`, role: 'assistant', text: marker, status: 'complete', usageSummary: { reasoningEffort: effort } },
    ]);
  };
  const fetcher = async (url, options) => {
    const path = new URL(url).pathname, method = options.method;
    state.calls.push(`${method} ${path}`);
    const body = options.body;
    const value = body && typeof body === 'string' && options.headers['content-type'] === 'application/json'
      ? JSON.parse(body) : {};
    if (path.startsWith('/public/webhooks/incoming/')) {
      const source = state.sources.get(path.split('/').at(-1));
      if (!source || !source.enabled) return response({}, 404);
      const headers = options.headers;
      let valid;
      if (headers.authorization) valid = headers.authorization === `Bearer ${source.credential}`;
      else if (source.kind === 'generic') {
        valid = headers['x-webhook-signature'] === `sha256=${createHmac('sha256', source.signingSecret)
          .update(`${headers['x-webhook-timestamp']}.${body}`).digest('hex')}`;
      } else {
        const prefix = `v1\n${headers['x-index-timestamp']}\n${headers['x-index-delivery']}\n${headers['x-index-trigger']}\n1\n`;
        valid = headers['x-index-signature'] === createHmac('sha256', source.signingSecret).update(prefix).update(body).digest('hex');
      }
      if (!valid) return response({ message: 'private-service-rejection-marker' }, 401);
      const isTest = headers['x-index-test'] === 'true';
      const deliveryId = source.kind === 'generic' ? value.eventId : headers['x-index-delivery'] ?? Buffer.from(body).toString('base64');
      const key = `${source.id}:${deliveryId}`;
      let event = state.deliveries.get(key);
      if (!event) {
        event = { id: randomUUID(), sourceId: source.id,
          text: source.kind === 'generic' ? source.textPath ? value.event.message.text : value.text : 'Test',
          status: isTest ? 'test' : 'awaiting_routing' };
        state.deliveries.set(key, event); state.events.set(event.id, event);
        if (!isTest && source.routingMode === 'fixed') execute(event, source.fallbackBotId, state.bots.get(source.fallbackBotId).reasoningEffort);
      }
      return response({ accepted: true, eventId: event.id, status: event.status }, 202);
    }
    assert.equal(options.headers.authorization, 'Bearer never-print-id-token');
    if (method === 'GET' && path === '/bootstrap') {
      if (failCleanupBootstrap && state.unknownSourceCreated) return response({}, 503);
      return response({ bots: [{ id: 'chief', systemRole: 'chief', templateId: 'chief' }, ...state.bots.values()],
        botTemplates: [{ id: 'chief' }, { id: 'research' }] });
    }
    if (path === '/billing') return response({ creditsRemaining: credits, privateBilling: 'never-print-billing' });
    if (method === 'POST' && path === '/bots') {
      assert.ok(value.name.length <= 48, 'Fixture name must satisfy the live bot name contract');
      const bot = { ...value, id: randomUUID() }; state.bots.set(bot.id, bot);
      state.conversations.set(bot.id, []); return response(bot, 201);
    }
    if (path.startsWith('/bots/')) {
      const botId = path.split('/')[2];
      if (method === 'POST' && path.endsWith('/cancel')) {
        if (cancelRace === 'complete') state.conversations.get(botId).find((message) => message.role === 'assistant').status = 'complete';
        return response({ message: 'never-print-cancellation-conflict' }, 409);
      }
      if (method === 'GET') return response({ messages: state.conversations.get(botId) });
      if (method === 'DELETE') { state.bots.delete(botId); return response({ deleted: true }); }
    }
    if (method === 'POST' && path === '/webhook-sources') {
      const source = { ...value, id: randomUUID(), credential: `never-print-credential-${randomUUID()}`,
        signingSecret: `never-print-signing-${randomUUID()}` };
      state.sources.set(source.id, source);
      if (loseCreatedSourceResponse) {
        state.unknownSourceCreated = true;
        throw new Error('never-print-unknown-create-response');
      }
      const { credential, signingSecret, ...publicSource } = source;
      return response({ source: publicSource, credential, signingSecret }, 201);
    }
    if (method === 'GET' && path === '/webhook-sources') return response({ sources: [...state.sources.values()] });
    if (path.startsWith('/webhook-sources/')) {
      const sourceId = path.split('/')[2], source = state.sources.get(sourceId);
      if (method === 'DELETE') { state.sources.delete(sourceId); return response({ deleted: true }); }
      if (method === 'PUT') { Object.assign(source, value); return response({ source }); }
      if (path.endsWith('/rotate')) {
        Object.assign(source, { credential: `never-print-new-credential-${randomUUID()}`, signingSecret: `never-print-new-signing-${randomUUID()}` });
        return response({ source, credential: source.credential, signingSecret: source.signingSecret });
      }
    }
    if (path === '/webhook-events') return response({ events: [...state.events.values()] });
    if (path.startsWith('/devices/')) {
      const deviceId = path.split('/')[2];
      if (method === 'PUT') { state.devices.add(deviceId); return response({ registered: true }); }
      if (method === 'DELETE') { state.devices.delete(deviceId); return response({ registered: false }); }
      if (method === 'GET') {
        const event = [...state.events.values()].find((item) => item.status === 'awaiting_routing');
        if (!event) return response({ requests: [] });
        const source = state.sources.get(event.sourceId), bot = state.bots.get(source.allowedBotIds[0]);
        return response({ requests: [{ id: event.id, text: event.text, bots: [bot],
          modelId: 'StrandsAgents/strands-decider-2B-qwen3.5-v1-2610',
          modelRevision: '216d1ccb46a9e9b036eb9187b248db98480f77d4', requestDigest: 'digest', leaseToken: 'never-print-lease' }] });
      }
      if (method === 'POST') {
        if (failLocalSubmission) {
          if (cancelRace && !state.pendingTurnId) {
            const botId = state.sources.get(state.events.get(path.split('/')[4]).sourceId).allowedBotIds[0];
            state.pendingTurnId = randomUUID();
            state.conversations.set(botId, [{ id: `${state.pendingTurnId}-assistant`, role: 'assistant', status: 'running' }]);
          }
          return response({ message: 'never-print-reply-body' }, 500);
        }
        const event = state.events.get(path.split('/')[4]);
        assert.equal(value.confidence, (2 * value.probabilities[value.botId] - 1));
        event.routingDecision = { ...value, method: 'local' };
        execute(event, value.botId, value.reasoningEffort);
        return response({ accepted: true, status: event.status });
      }
    }
    throw new Error('Unexpected mock route');
  };
  return { state, fetcher };
}

test('smoke caps paid turns at two and cleans every fixture with explicit simulated-model evidence', async () => {
  const { state, fetcher } = mockCloud();
  const result = await runWebhookSmoke({ apiUrl: 'https://api.example.test', idToken: 'never-print-id-token', fetcher, sleep: async () => {} });
  assert.equal(result.passed, true);
  assert.equal(state.turns, 2);
  assert.equal(state.bots.size + state.sources.size + state.devices.size, 0);
  assert.equal(result.physicalAPNsDeliveryVerified, false);
  assert.match(result.localDecisionEvidence, /simulated/);
  assert.doesNotMatch(JSON.stringify(result), /never-print|webhook-fixed-|webhook-local-/);
});

test('insufficient credits stop before any fixture creation or public webhook', async () => {
  const { state, fetcher } = mockCloud({ credits: 1 });
  await assert.rejects(runWebhookSmoke({ apiUrl: 'https://api.example.test', idToken: 'never-print-id-token', fetcher }), /at least two remaining credits/);
  assert.deepEqual(state.calls, ['GET /bootstrap', 'GET /billing']);
  assert.equal(state.turns, 0);
});

test('a local transport failure cleans existing resources without leaking service messages or secrets', async () => {
  const { state, fetcher } = mockCloud({ failLocalSubmission: true });
  await assert.rejects(runWebhookSmoke({ apiUrl: 'https://api.example.test', idToken: 'never-print-id-token', fetcher, sleep: async () => {} }), (error) => {
    assert.equal(error.smokeSummary.cleanupSucceeded, true);
    assert.doesNotMatch(error.message + JSON.stringify(error.smokeSummary), /never-print|private-service/);
    return true;
  });
  assert.equal(state.bots.size + state.sources.size + state.devices.size, 0);
  assert.equal(state.turns, 1);
});

test('unknown create outcomes are discovered by exact run name and cleaned without replaying creates', async () => {
  const { state, fetcher } = mockCloud({ loseCreatedSourceResponse: true });
  await assert.rejects(runWebhookSmoke({ apiUrl: 'https://api.example.test', idToken: 'never-print-id-token', fetcher, sleep: async () => {} }), (error) => {
    assert.equal(error.smokeSummary.cleanupSucceeded, true);
    assert.doesNotMatch(error.message, /never-print/);
    return true;
  });
  assert.equal(state.bots.size + state.sources.size + state.devices.size, 0);
  assert.equal(state.calls.filter((call) => call === 'POST /webhook-sources').length, 1);
  assert.equal(state.turns, 0);
});

test('source discovery still cleans an unknown create when cleanup bootstrap is unavailable', async () => {
  const { state, fetcher } = mockCloud({ loseCreatedSourceResponse: true, failCleanupBootstrap: true });
  await assert.rejects(runWebhookSmoke({ apiUrl: 'https://api.example.test', idToken: 'never-print-id-token', fetcher, sleep: async () => {} }), (error) => {
    assert.equal(error.smokeSummary.cleanupSucceeded, false, 'Unverified bot discovery must remain visible');
    return true;
  });
  assert.ok(state.calls.includes('GET /webhook-sources'));
  assert.equal(state.sources.size + state.bots.size, 0);
});

for (const cancelRace of ['complete', 'active']) {
  test(`cancellation conflict with ${cancelRace} turn still attempts bot deletion and reports cleanup truthfully`, async () => {
    const { state, fetcher } = mockCloud({ failLocalSubmission: true, cancelRace });
    await assert.rejects(runWebhookSmoke({ apiUrl: 'https://api.example.test', idToken: 'never-print-id-token', fetcher, sleep: async () => {} }), (error) => {
      assert.equal(error.smokeSummary.cleanupSucceeded, cancelRace === 'complete');
      assert.doesNotMatch(error.message + JSON.stringify(error.smokeSummary), /never-print/);
      return true;
    });
    const cancelIndex = state.calls.findIndex((call) => call.endsWith('/cancel'));
    assert.ok(cancelIndex >= 0);
    assert.match(state.calls[cancelIndex + 1], /^GET \/bots\/[^/]+\/messages$/);
    assert.match(state.calls[cancelIndex + 2], /^DELETE \/bots\//);
    assert.equal(state.bots.size + state.sources.size + state.devices.size, 0);
  });
}

test('test payload helpers sign exact JSON and binary multipart bytes without exposing key material', () => {
  const generic = genericDelivery('unit-signing-key', { text: 'question' }, '1700000000');
  assert.equal(generic.headers['x-webhook-signature'], `sha256=${createHmac('sha256', 'unit-signing-key').update(`1700000000.${generic.body}`).digest('hex')}`);
  const pebble = pebbleTestDelivery('unit-signing-key', 'delivery-1', '1700000000');
  assert.ok(Buffer.isBuffer(pebble.body));
  assert.ok(pebble.body.includes(Buffer.from([0, 255, 13, 10, 128])));
  assert.equal(pebble.headers['x-index-signature'], createHmac('sha256', 'unit-signing-key').update('v1\n1700000000\ndelivery-1\ntest-event\n1\n').update(pebble.body).digest('hex'));
  assert.doesNotMatch(JSON.stringify(pebble.headers), /unit-signing-key/);
});
