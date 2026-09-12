import assert from 'node:assert/strict';
import test from 'node:test';

import { browserError, hasBrowserCapability, isLiveViewUrl, liveViewDeadline, shouldUseBotBrowserForChatLinks, withoutLiveView } from './browser-policy.ts';
import { ApiClientError } from '@froggybot/client';
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

test('chat links use the private browser only when the direct bot can browse', () => {
  assert.equal(shouldUseBotBrowserForChatLinks({ toolIds: ['browser'] }, false), true);
  assert.equal(shouldUseBotBrowserForChatLinks({ toolIds: [], extraToolIds: ['browser'] }, false), true);
  assert.equal(shouldUseBotBrowserForChatLinks({ toolIds: [] }, false), false);
  assert.equal(shouldUseBotBrowserForChatLinks({ toolIds: ['browser'] }, true), false);
  assert.equal(shouldUseBotBrowserForChatLinks(undefined, false), false);
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

test('stable error codes distinguish conflicts without coupling UI to server prose', () => {
  const conflict = (code) => browserError(new ApiClientError(409, code, url), 'open');
  assert.match(conflict('browser_bot_busy'), /bot is working/);
  assert.match(conflict('browser_handoff_incomplete'), /Disconnect/);
  assert.doesNotMatch(conflict('browser_handoff_incomplete'), /stop.*chat/);
  assert.match(conflict('browser_operation_in_progress'), /Check status/);
  assert.match(conflict('browser_session_expired'), /session ended/);
  assert.doesNotMatch(conflict('unknown'), /Signature/);
});
