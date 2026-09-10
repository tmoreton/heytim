import assert from 'node:assert/strict';
import test from 'node:test';

import { browserError, hasBrowserCapability, isLiveViewUrl, liveViewDeadline, withoutLiveView } from './browser-policy.ts';
import { viewerLocation } from './viewer-location.ts';

const url = 'https://bedrock-agentcore.us-east-1.amazonaws.com/browser-streams/aws.browser.v1/sessions/test/live-view?X-Amz-Signature=test';

test('accepts only signed AgentCore Live View endpoints', () => {
  assert.equal(isLiveViewUrl(url), true);
  for (const bad of [undefined, 'javascript:alert(1)', url.replace('https:', 'http:'), url.replace('amazonaws.com', 'amazonaws.com.attacker.test'), url.replace('bedrock-agentcore.', 'evil.'), url.replace('live-view', 'automation'), url.split('?')[0], `${url}#fragment`, url.replace('https://', 'https://user:pass@')]) {
    assert.equal(isLiveViewUrl(bad), false);
  }
});

test('viewer uses only a static trusted shell URL, never query credentials', () => {
  assert.equal(viewerLocation('https://froggybot.com'), 'https://froggybot.com/bot-browser/index.html');
  assert.equal(viewerLocation('http://localhost:8082'), 'http://localhost:8082/bot-browser/index.html');
  assert.throws(() => viewerLocation('http://example.test'));
  assert.throws(() => viewerLocation('https://froggybot.com?secret=value'));
});

test('capability checks include explicit and skill-derived browser tool ids', () => {
  assert.equal(hasBrowserCapability({ toolIds: ['browser'] }), true);
  assert.equal(hasBrowserCapability({ toolIds: [], extraToolIds: ['browser'] }), true);
  assert.equal(hasBrowserCapability({ toolIds: ['code_interpreter'] }), false);
});

test('view lifetime fails closed and never exceeds either expiry', () => {
  assert.equal(liveViewDeadline(), 0);
  assert.equal(liveViewDeadline({ liveViewExpiresAt: 'invalid' }), 0);
  const state = { liveViewUrl: url, liveViewExpiresAt: '2026-09-09T21:05:00Z', sessionExpiresAt: '2026-09-09T21:00:00Z', botId: 'b', status: 'human_control' };
  assert.equal(liveViewDeadline(state), Date.parse(state.sessionExpiresAt));
  assert.deepEqual(withoutLiveView(state), { sessionExpiresAt: state.sessionExpiresAt, botId: 'b', status: 'human_control' });
});

test('user-facing errors never expose provider details or signed credentials', () => {
  const providerError = new Error(url);
  assert.ok(!browserError(providerError, 'open').includes('Signature'));
  assert.match(browserError({ status: 409 }, 'open'), /Check status/);
  assert.match(browserError(providerError, 'resume'), /already have resumed/);
});

test('conflicts distinguish active work from failed handoffs without leaking unknown details', () => {
  const conflict = (message) => browserError(Object.assign(new Error(message), { status: 409 }), 'open');
  assert.match(conflict('Wait for the bot to finish or stop it before opening its browser'), /bot is working/);
  assert.match(conflict('Finish or close the previous browser handoff first'), /Disconnect/);
  assert.doesNotMatch(conflict('Finish or close the previous browser handoff first'), /stop.*chat/);
  assert.match(conflict('A browser operation is still in progress'), /Check status/);
  assert.match(conflict('The browser session expired. Open it again before resuming'), /session ended/);
  assert.doesNotMatch(conflict(url), /Signature/);
});
