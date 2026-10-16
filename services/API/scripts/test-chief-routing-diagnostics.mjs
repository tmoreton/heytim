import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { test } from 'node:test';
import { runChiefRoutingDiagnostics } from './chief-routing-diagnostics.mjs';

const chiefID = 'chief-id';
// Chief create_bot stores ai-${mutation_id}, not a bare UUID.
const targetID = 'ai-10000000-0000-4000-8000-000000000001';
const otherID = 'ai-10000000-0000-4000-8000-000000000002';
const marker = 'HEYTIM_CHIEF_ROUTE_0123456789abcdef0123456789abcdef';
const task = `Reply exactly ${marker} and nothing else.`;
const prompt = (id = targetID) => `Route one task to the existing bot with ID ${id} using route_to_bot. Forward exactly this task text: ${JSON.stringify(task)}. The teammate must answer in its own chat. Queue it once and finish without answering the task yourself.`;
const user = (id = 'route-turn', text = prompt(), createdAt = '2026-10-16T02:30:00Z') =>
  ({ id: `${id}-user`, role: 'user', text, createdAt });
const assistant = (id = 'route-turn', values = {}) => ({ id: `${id}-assistant`, role: 'assistant',
  status: 'complete', text: 'A private model answer must never appear in diagnostics.', ...values });
const redacted = (value) => assert.doesNotMatch(JSON.stringify(value),
  /never-print|private|chief-id|route-turn|10000000-|HEYTIM_CHIEF_ROUTE|Forward exactly|Using route to bot/);

function mock({ chiefMessages = [user(), assistant()], targetMessages = [], targetExists = true,
  target404 = false, bootstrap, failure } = {}) {
  const calls = [];
  const fetcher = async (url, options) => {
    calls.push(new URL(url).pathname);
    assert.equal(options.method, 'GET', 'Diagnostics must never mutate or invoke the model');
    assert.equal(options.body, undefined);
    assert.equal(options.redirect, 'error');
    assert.equal(options.headers.authorization, 'Bearer never-print-token');
    if (failure) throw new Error('never-print-token private-provider-failure');
    const path = new URL(url).pathname;
    if (path === '/bootstrap') return Response.json(bootstrap ?? { bots: [
      { id: chiefID, systemRole: 'chief', templateId: 'chief' },
      ...(targetExists ? [{ id: targetID }, { id: otherID }] : []),
    ] });
    if (path === `/bots/${chiefID}/messages`) return Response.json({ messages: chiefMessages });
    if ([targetID, otherID].some((id) => path === `/bots/${id}/messages`)) {
      return Response.json({ messages: targetMessages }, { status: target404 ? 404 : 200 });
    }
    throw new Error('Unexpected request');
  };
  return { calls, fetcher };
}
const run = (fetcher, config = {}) => runChiefRoutingDiagnostics({
  apiUrl: 'https://api.example.test', idToken: 'never-print-token', fetcher, ...config });

test('GET-only diagnostics distinguish completed Chief with no target handoff without claiming tool absence', async () => {
  const cloud = mock();
  const result = await run(cloud.fetcher);
  assert.equal(result.diagnosticsCompleted, true);
  assert.equal(result.syntheticRouteFound, true);
  assert.equal(result.assistantStatus, 'complete');
  assert.equal(result.configurationChanged, false);
  assert.equal(result.routeToolActivityObserved, false);
  assert.equal(result.targetHandoffState, 'no_handoff_observed');
  assert.deepEqual(cloud.calls, ['/bootstrap', `/bots/${chiefID}/messages`, `/bots/${targetID}/messages`]);
  assert.equal('passed' in result, false);
  redacted(result);
});

test('only the exact synthetic prompt qualifies; near matches, pasted text and malformed markers do not', async () => {
  for (const text of [`Copied: ${prompt()}`, `${prompt()}\n`, prompt().replace('Queue it once', 'Queue twice'),
    prompt().replace(marker, 'HEYTIM_CHIEF_ROUTE_not-a-uuid'), prompt().replace(targetID, '../private'),
    prompt().replace(targetID, targetID.slice(3))]) {
    const cloud = mock({ chiefMessages: [user('route-turn', text), assistant()] });
    const result = await run(cloud.fetcher);
    assert.equal(result.syntheticRouteFound, false);
    assert.equal(result.targetHandoffState, 'not_checked');
    assert.equal(cloud.calls.length, 2);
    redacted(result);
  }
});

test('selects the newest synthetic route timestamp rather than response order or unrelated owner text', async () => {
  const cloud = mock({ chiefMessages: [
    user('new', prompt(otherID), '2026-10-16T03:00:00Z'), assistant('new', { configurationChanged: true }),
    user('old', prompt(), '2026-10-16T02:00:00Z'), assistant('old', { status: 'error' }),
    user('unrelated', 'private unrelated owner conversation', '2026-10-16T04:00:00Z'),
  ] });
  const result = await run(cloud.fetcher);
  assert.equal(result.assistantStatus, 'complete');
  assert.equal(result.configurationChanged, true);
  assert.equal(cloud.calls.at(-1), `/bots/${otherID}/messages`);
  redacted(result);
});

test('exact fixed activity labels become booleans; narration and arbitrary activity stay private', async () => {
  const cloud = mock({ chiefMessages: [user(), assistant('route-turn', { activity: [
    'private model narration using route_to_bot is not a fixed tool label',
    'Using route to bot', 'Using list bot options', { text: 'never-print-token' },
  ] })] });
  const result = await run(cloud.fetcher);
  assert.equal(result.routeToolActivityObserved, true);
  assert.equal(result.listBotOptionsActivityObserved, true);
  redacted(result);
});

test('assistant statuses are closed enums and configurationChanged requires a boolean', async () => {
  for (const [input, expected] of [['running', 'running'], ['awaiting_approval', 'awaiting_approval'],
    ['error', 'error'], ['cancelled', 'cancelled'], ['never-print-status', 'unknown']]) {
    const cloud = mock({ chiefMessages: [user(), assistant('route-turn', {
      status: input, configurationChanged: 'private-truthy-value',
    })] });
    const result = await run(cloud.fetcher);
    assert.equal(result.assistantStatus, expected);
    assert.equal(result.configurationChanged, false);
    redacted(result);
  }
  const result = await run(mock({ chiefMessages: [user()] }).fetcher);
  assert.equal(result.assistantStatus, 'missing');
});

test('classifies known model errors and refusal without returning arbitrary text', async () => {
  for (const [text, expected] of [
    ['OpenRouter authentication is unavailable. never-print-token', 'authentication_unavailable'],
    ['Bot not found or name is ambiguous; call list_bot_options first private-target', 'routing_target_rejected'],
    ['Only one bot change can be made in a single message', 'mutation_limit_rejected'],
    ['Chief could not queue this task. private target', 'routing_dispatch_failed'],
    ['That teammate is already working. private task', 'teammate_busy'],
    ["I cannot route that task to another bot. private content", 'model_declined'],
    ['never-print-token arbitrary hostile text', 'none_recognized'],
  ]) {
    const result = await run(mock({ chiefMessages: [user(), assistant('route-turn', { text })] }).fetcher);
    assert.equal(result.assistantTextClassification, expected);
    redacted(result);
  }
});

test('unlisted fixtures and confirmed 404 races are distinguished from no-handoff evidence', async () => {
  for (const config of [{ targetExists: false }, { target404: true }]) {
    const cloud = mock(config);
    const result = await run(cloud.fetcher);
    assert.equal(result.targetListed, config.targetExists !== false);
    assert.equal(result.targetDeleted, config.target404 === true);
    assert.equal(result.targetHandoffState, config.target404 ? 'target_deleted' : 'target_not_listed');
    assert.equal(result.targetHandoffAssistantStatus, 'missing');
    assert.equal(cloud.calls.length, config.targetExists === false ? 2 : 3);
    redacted(result);
  }
});

test('handoff row, exact task and child execution state are reported independently', async () => {
  for (const childStatus of ['pending', 'running', 'error', 'complete']) {
    const cloud = mock({ targetMessages: [
      { id: 'private-child-user', role: 'user', source: 'bot_route', text: task },
      { id: 'private-child-assistant', role: 'assistant', status: childStatus, text: 'never-print-child-answer' },
    ] });
    const result = await run(cloud.fetcher);
    assert.equal(result.targetHandoffState, 'matching_handoff_observed');
    assert.equal(result.targetHandoffCount, 1);
    assert.equal(result.targetMatchingTaskCount, 1);
    assert.equal(result.targetHandoffAssistantStatus, childStatus);
    redacted(result);
  }
  const result = await run(mock({ targetMessages: [
    { id: 'private-child-user', role: 'user', source: 'bot_route', text: 'private different task' },
  ] }).fetcher);
  assert.equal(result.targetHandoffState, 'different_handoff_observed');
  assert.equal(result.targetMatchingTaskCount, 0);
  redacted(result);
});

test('hostile configuration, malformed API payloads and transport failures emit only fixed error codes', async () => {
  for (const apiUrl of ['https://never-print-user:private-password@example.test',
    'https://example.test/?token=never-print-token', 'https://example.test/#never-print-token', 'file:///private']) {
    const cloud = mock();
    await assert.rejects(run(cloud.fetcher, { apiUrl }), (error) => {
      assert.equal(error.diagnosticCode, 'configuration_invalid');
      redacted({ code: error.diagnosticCode, message: error.message });
      return true;
    });
    assert.equal(cloud.calls.length, 0);
  }
  for (const config of [{ bootstrap: { bots: 'never-print-payload' } }, { failure: true }]) {
    await assert.rejects(run(mock(config).fetcher), (error) => {
      assert.ok(['bootstrap_invalid', 'bootstrap_transport'].includes(error.diagnosticCode));
      redacted({ code: error.diagnosticCode, message: error.message });
      return true;
    });
  }
});

test('CLI configuration failure emits a fixed sanitized object', async () => {
  await assert.rejects(promisify(execFile)(process.execPath, [
    new URL('./chief-routing-diagnostics.mjs', import.meta.url).pathname,
  ], { env: {}, timeout: 10_000 }), (error) => {
    assert.equal(error.code, 1);
    assert.equal(error.stdout, '');
    assert.deepEqual(JSON.parse(error.stderr), { diagnosticsCompleted: false, code: 'configuration_missing' });
    return true;
  });
});
