import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { promisify } from 'node:util';
import { runChiefSmoke } from './authenticated-chief-test.mjs';

const catalog = JSON.parse(readFileSync(new URL('../../../catalog/catalog.json', import.meta.url), 'utf8'));
const chiefTemplate = catalog.bots.find((bot) => bot.id === 'chief');
const idToken = 'never-print-token';
const summaryIsRedacted = (value) => assert.doesNotMatch(JSON.stringify(value),
  /never-print|private-billing|private-provider|private-model|HEYTIM_CHIEF_ROUTE|Chief Check/);

function mockCloud({ credits = 4, chiefVersion = 9, missingTool = false, skillLimit = 20,
  createNoOp = false, editNoOp = false, duplicateRoute = false, wrongTask = false,
  wrongReply = false, childError = false, loseCreateResponse = false, cleanupFailure = false,
  chiefBusy = false, unexpectedCreate = false } = {}) {
  const chief = { ...chiefTemplate, id: 'chief-id', systemRole: 'chief', templateId: 'chief', templateVersion: chiefVersion,
    toolIds: missingTool ? chiefTemplate.toolIds.slice(1) : chiefTemplate.toolIds };
  const unrelated = { id: 'unrelated-id', name: 'Existing teammate', toolIds: [], skillIds: [] };
  const state = { bots: new Map([[chief.id, chief], [unrelated.id, unrelated]]), calls: [],
    conversations: new Map([[chief.id, []]]), createdIDs: [], chiefTurns: 0, deletions: [] };
  if (chiefBusy) state.conversations.get(chief.id).push({ id: 'unrelated-work-assistant', role: 'assistant', status: 'running' });
  const response = (value, status = 200) => new Response(JSON.stringify(value), { status,
    headers: { 'content-type': 'application/json' } });
  const fetcher = async (url, options) => {
    const path = new URL(url).pathname, method = options.method;
    state.calls.push(`${method} ${path}`);
    assert.equal(options.headers.authorization, `Bearer ${idToken}`);
    const value = options.body ? JSON.parse(options.body) : {};
    if (method === 'GET' && path === '/bootstrap') {
      return response({ bots: [...state.bots.values()], constraints: { maxSkillsPerBot: skillLimit } });
    }
    if (method === 'GET' && path === '/billing') return response({ creditsRemaining: credits,
      privateBilling: 'private-billing-never-print' });
    if (method === 'POST' && path === `/bots/${chief.id}/messages`) {
      const turnId = `chief-turn-${++state.chiefTurns}`;
      state.conversations.get(chief.id).push(
        { id: `${turnId}-user`, role: 'user', text: value.text, status: 'complete' },
        { id: `${turnId}-assistant`, role: 'assistant', text: 'private-model-answer', status: 'complete' },
      );
      if (state.chiefTurns === 1 && !createNoOp) {
        const match = value.text.match(/exact configuration: (\{.*?\})\./);
        assert.ok(match, 'The create prompt must include concrete configuration');
        const bot = { ...JSON.parse(match[1]), id: 'created-fixture' };
        assert.ok(bot.name.length <= 48);
        assert.deepEqual(bot.toolIds, []);
        assert.deepEqual(bot.skillIds, []);
        if (unexpectedCreate) bot.name = 'Unexpected new bot';
        state.bots.set(bot.id, bot);
        state.createdIDs.push(bot.id);
        state.conversations.set(bot.id, []);
        if (loseCreateResponse) throw new Error('private-provider-unknown-outcome');
      } else if (state.chiefTurns === 2 && !editNoOp) {
        const match = value.text.match(/ID ([^ ]+) to exactly ("[^"]+")/);
        assert.ok(match, 'The edit prompt must specify an exact existing bot and tagline');
        state.bots.get(match[1]).tagline = JSON.parse(match[2]);
      } else if (state.chiefTurns === 3) {
        assert.match(value.text, /using route_to_bot/);
        const match = value.text.match(/Forward exactly this task text: ("[^"]+")/);
        const task = JSON.parse(match[1]);
        const marker = task.match(/Reply exactly (\S+) and nothing else\./)[1];
        const botID = value.text.match(/ID ([^ ]+) using/)[1];
        const turns = duplicateRoute ? 2 : 1;
        for (let index = 0; index < turns; index += 1) {
          const childID = `routed-${index}`;
          state.conversations.get(botID).push(
            { id: `${childID}-user`, role: 'user', source: 'bot_route', text: wrongTask ? 'private-history-leak' : task, status: 'complete' },
            { id: `${childID}-assistant`, role: 'assistant', text: wrongReply ? 'private-model-wrong-answer' : marker,
              status: childError ? 'error' : 'complete' },
          );
        }
      }
      return response({ turnId, status: 'pending' }, 202);
    }
    const botID = path.split('/')[2];
    if (method === 'GET' && path.endsWith('/messages')) return response({ messages: state.conversations.get(botID) ?? [] });
    if (method === 'DELETE' && path.startsWith('/bots/')) {
      assert.equal(botID, 'created-fixture', 'Cleanup must only delete the bot created by this run');
      if (cleanupFailure) return response({ message: 'private-provider-delete-failure' }, 503);
      state.deletions.push(botID);
      state.bots.delete(botID);
      return response({ deleted: true });
    }
    throw new Error('private-provider-unexpected-request');
  };
  return { state, fetcher };
}

const run = (fetcher) => runChiefSmoke({ apiUrl: 'https://api.example.test', idToken, fetcher,
  sleep: async () => {}, timeoutMs: 1000 });

test('Chief defaults, real create/edit/routing paths, exact child answer, and scoped cleanup are required', async () => {
  const { state, fetcher } = mockCloud();
  const result = await run(fetcher);
  assert.deepEqual(result, { passed: true,
    completed: ['chief_defaults', 'credit_preflight', 'chief_create', 'chief_edit', 'chief_routing'],
    cleanupSucceeded: true, chiefTurns: 3, routedTurnsVerified: 1 });
  assert.equal(state.chiefTurns, 3);
  assert.deepEqual(state.deletions, ['created-fixture']);
  assert.deepEqual([...state.bots.keys()], ['chief-id', 'unrelated-id']);
  assert.ok(!state.calls.includes('POST /bots'), 'The smoke must exercise Chief creation rather than direct API creation');
  assert.ok(!state.calls.some((call) => call.includes('/account')));
  summaryIsRedacted(result);
});

test('fewer than four remaining credits stops before sending turns or creating fixtures', async () => {
  const { state, fetcher } = mockCloud({ credits: 3 });
  await assert.rejects(run(fetcher), (error) => {
    assert.equal(error.smokeSummary.code, 'insufficient_credits');
    summaryIsRedacted(error.smokeSummary);
    return true;
  });
  assert.deepEqual(state.calls, ['GET /bootstrap', 'GET /billing']);
  assert.equal(state.chiefTurns, 0);
});

test('old Chief defaults and wrong published skill limits fail before billing or mutations', async () => {
  for (const options of [{ chiefVersion: 8 }, { missingTool: true }, { skillLimit: 12 }]) {
    const { state, fetcher } = mockCloud(options);
    await assert.rejects(run(fetcher), (error) => {
      assert.equal(error.smokeSummary.cleanupSucceeded, true);
      summaryIsRedacted(error.smokeSummary);
      return true;
    });
    assert.deepEqual(state.calls, ['GET /bootstrap']);
  }
});

test('an already working Chief is preserved and receives no test turn or cancellation', async () => {
  const { state, fetcher } = mockCloud({ chiefBusy: true });
  await assert.rejects(run(fetcher), (error) => {
    assert.equal(error.smokeSummary.code, 'chief_busy');
    assert.equal(error.smokeSummary.cleanupSucceeded, true);
    return true;
  });
  assert.equal(state.chiefTurns, 0);
  assert.deepEqual(state.calls, ['GET /bootstrap', 'GET /billing', 'GET /bots/chief-id/messages']);
});

test('an unexpected new bot is reported as unresolved without deleting it or existing bots', async () => {
  const { state, fetcher } = mockCloud({ unexpectedCreate: true });
  await assert.rejects(run(fetcher), (error) => {
    assert.equal(error.smokeSummary.code, 'unexpected_new_bot');
    assert.equal(error.smokeSummary.cleanupSucceeded, false);
    summaryIsRedacted(error.smokeSummary);
    return true;
  });
  assert.deepEqual(state.deletions, []);
  assert.equal(state.bots.size, 3);
});

test('a model statement without applied creation or edit does not pass', async () => {
  for (const options of [{ createNoOp: true }, { editNoOp: true }]) {
    const { state, fetcher } = mockCloud(options);
    await assert.rejects(run(fetcher), (error) => {
      assert.ok(['chief_create_not_applied', 'chief_edit_not_applied'].includes(error.smokeSummary.code));
      assert.equal(error.smokeSummary.cleanupSucceeded, true);
      summaryIsRedacted(error.smokeSummary);
      return true;
    });
    assert.deepEqual([...state.bots.keys()], ['chief-id', 'unrelated-id']);
  }
});

test('duplicate handoffs, unexpected forwarded text, wrong child replies, and child errors fail with scoped cleanup', async () => {
  for (const options of [{ duplicateRoute: true }, { wrongTask: true }, { wrongReply: true }, { childError: true }]) {
    const { state, fetcher } = mockCloud(options);
    await assert.rejects(run(fetcher), (error) => {
      assert.equal(error.smokeSummary.passed, false);
      assert.equal(error.smokeSummary.cleanupSucceeded, true);
      summaryIsRedacted(error.smokeSummary);
      assert.doesNotMatch(error.message, /private-|never-print/);
      return true;
    });
    assert.deepEqual(state.deletions, ['created-fixture']);
  }
});

test('an unknown create response is discovered by exact fixture identity and cleaned without replay', async () => {
  const { state, fetcher } = mockCloud({ loseCreateResponse: true });
  await assert.rejects(run(fetcher), (error) => {
    assert.equal(error.smokeSummary.code, 'chief_turn_transport');
    assert.equal(error.smokeSummary.cleanupSucceeded, true);
    summaryIsRedacted(error.smokeSummary);
    return true;
  });
  assert.equal(state.chiefTurns, 1);
  assert.deepEqual(state.deletions, ['created-fixture']);
});

test('cleanup failure is reported without exposing response bodies or deleting Chief/account', async () => {
  const { state, fetcher } = mockCloud({ cleanupFailure: true });
  await assert.rejects(run(fetcher), (error) => {
    assert.equal(error.smokeSummary.code, 'cleanup_failed');
    assert.equal(error.smokeSummary.cleanupSucceeded, false);
    summaryIsRedacted(error.smokeSummary);
    return true;
  });
  assert.deepEqual(state.deletions, []);
  assert.ok(state.bots.has('chief-id') && state.bots.has('unrelated-id'));
});

test('CLI failures emit only a fixed structured result', async () => {
  await assert.rejects(promisify(execFile)(process.execPath, [
    new URL('./authenticated-chief-test.mjs', import.meta.url).pathname,
  ], { env: {}, timeout: 10_000 }), (error) => {
    assert.equal(error.code, 1);
    assert.deepEqual(JSON.parse(error.stderr), { passed: false, code: 'configuration_missing' });
    assert.equal(error.stdout, '');
    return true;
  });
});
