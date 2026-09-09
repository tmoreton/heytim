// Run against an Expo dev server; only the isolated, local preview is used.
// Example: node scripts/chat-layout-browser-test.mjs http://localhost:8082
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const origin = new URL(process.argv[2] ?? 'http://localhost:8082');
assert.ok(['localhost', '127.0.0.1'].includes(origin.hostname), 'Use a local dev server, never a real account.');
const session = `frogbot-layout-${process.pid}`;
const artifacts = mkdtempSync(join(tmpdir(), 'frogbot-chat-layout-'));
// Resolve the pinned CLI once: parallel npx invocations can race while updating its cache.
const executable = process.env.AGENT_BROWSER_BIN ?? execFileSync('npm', [
  'exec', '--yes', '--package=agent-browser@0.27.0', '--', 'which', 'agent-browser',
], { encoding: 'utf8', timeout: 60_000 }).trim();
console.log(`Browser evidence: ${artifacts}`);
const browser = (...args) => {
  const output = execFileSync(executable, ['--session', session, '--json', ...args], {
    encoding: 'utf8', timeout: 60_000, maxBuffer: 4 * 1024 * 1024,
  });
  const result = JSON.parse(output);
  assert.equal(result.success, true, result.error ?? output);
  return result.data;
};
const evaluate = (source) => browser('eval', source).result;
const snapshot = () => browser('snapshot', '-i');
const wait = (ms = 500) => browser('wait', String(ms));
const screenshot = (name) => browser('screenshot', join(artifacts, `${name}.png`));
const listSelector = '[data-testid="conversation-messages"]';
const tableSelector = '[data-testid="markdown-table-scroll"]';
const metrics = () => evaluate(`(() => {
  const list = document.querySelector('${listSelector}');
  return { top: list.scrollTop, height: list.scrollHeight, viewport: list.clientHeight,
    distance: list.scrollHeight - list.clientHeight - list.scrollTop,
    bodyWidth: document.body.scrollWidth, screenWidth: innerWidth };
})()`);

try {
  browser('set', 'viewport', '1280', '900');
  browser('open', new URL('/app?preview=1', origin).href);
  browser('wait', listSelector);
  snapshot();
  screenshot('desktop-initial');
  assert.deepEqual(browser('errors').errors, []);
  assert.ok(metrics().distance <= 64, 'Opening a conversation lands at its latest message.');

  browser('scroll', 'up', '450', '--selector', listSelector);
  wait();
  const history = metrics();
  assert.ok(history.distance > 100, `Scrolling can reach older messages: ${JSON.stringify(history)}`);
  browser('wait', '[aria-label="Jump to latest message"]');
  wait(1800);
  assert.ok(Math.abs(metrics().top - history.top) <= 2, 'History does not snap back after layout/polling.');
  screenshot('desktop-history');
  console.log('PASS: desktop scrolling and persistent history position');

  snapshot();
  browser('fill', '[aria-label="Message Weekend in Portland"]', 'Compare the weekend options for this preview test.');
  browser('click', '[aria-label="Send message"]');
  browser('scroll', 'up', '600', '--selector', listSelector);
  wait(500);
  const pendingHistory = metrics();
  assert.ok(pendingHistory.distance > 100);
  wait(5000);
  assert.ok(evaluate('document.body.innerText.includes("Decision: Portland, Maine")'), 'The new team answer actually arrived.');
  assert.ok(Math.abs(metrics().top - pendingHistory.top) <= 2, 'Incoming replies preserve the history position.');
  snapshot();
  browser('click', '[aria-label="Jump to latest message"]');
  wait();
  assert.ok(metrics().distance <= 64, 'Jump to latest returns to the newest answer.');
  console.log('PASS: incoming team replies do not interrupt reading; jump to latest works');

  browser('fill', '[aria-label="Message Weekend in Portland"]', 'Summarize the next steps in this preview.');
  browser('click', '[aria-label="Send message"]');
  wait(5000);
  assert.ok(metrics().distance <= 64, 'Replies still follow when already at the bottom.');
  snapshot();
  browser('click', '[aria-label="Chief"]');
  snapshot();
  browser('click', '[aria-label="Weekend in Portland"]');
  wait();
  assert.ok(metrics().distance <= 64, 'Switching rooms resets follow-to-latest.');
  console.log('PASS: bottom-follow and conversation switching');

  for (const width of [390, 375, 320, 1280, 1920]) {
    browser('set', 'viewport', String(width), width < 600 ? '844' : '900');
    evaluate(`document.querySelector('${listSelector}').scrollTop = 300`);
    wait();
    snapshot();
    const layout = evaluate(`(() => {
      const table = document.querySelector('${tableSelector}');
      const cells = [...table.querySelectorAll('div')].filter(e => getComputedStyle(e).borderTopWidth !== '0px').slice(0, 5);
      let bubble = table;
      while (bubble && getComputedStyle(bubble).backgroundColor !== 'rgb(233, 244, 238)') bubble = bubble.parentElement;
      return { width: table.clientWidth, contentWidth: table.scrollWidth, cellWidths: cells.map(e => e.clientWidth),
        bubbleRight: bubble.getBoundingClientRect().right, right: innerWidth,
        linkCount: table.querySelectorAll('[role="link"]').length };
    })()`);
    assert.equal(metrics().bodyWidth, width, 'Tables must not create page-level horizontal overflow.');
    assert.ok(layout.cellWidths[1] >= 280, 'Task words must not collapse into tiny columns.');
    assert.ok(layout.cellWidths[4] >= 280, 'Rationale text retains a readable column.');
    assert.equal(layout.linkCount, 1, 'Table links retain their semantics.');
    if (width < 600) {
      assert.ok(layout.right - layout.bubbleRight <= 14, 'Mobile bubble uses the available right-hand space.');
      assert.ok(layout.contentWidth > layout.width, 'Phone tables scroll instead of squeezing.');
      evaluate(`document.querySelector('${tableSelector}').scrollBy({ left: 550, behavior: 'instant' })`);
      wait();
      assert.ok(evaluate(`document.querySelector('${tableSelector}').scrollLeft`) > 100, 'Horizontal scrolling exposes remaining columns.');
      assert.equal(evaluate(`document.querySelectorAll('[aria-label="Message copied"]').length`), 0, 'Scrolling must not copy the message.');
      screenshot(`phone-${width}-scrolled-table`);
      evaluate(`document.querySelector('${tableSelector}').scrollLeft = 0`);
      screenshot(`phone-${width}-table`);
    } else {
      assert.ok(layout.width <= 650, 'Desktop keeps its bounded message width.');
      assert.ok(layout.right - layout.bubbleRight > 100, 'Desktop retains space outside the centered conversation.');
      assert.ok(layout.contentWidth > layout.width, 'Wide tables can scroll inside the bounded desktop bubble.');
      screenshot(`desktop-${width}-table`);
    }
    console.log(`PASS: ${width}px layout, mobile-only full-width bubbles, table sizing and links`);
  }

  assert.deepEqual(browser('errors').errors, [], 'No uncaught browser errors.');
  console.log(`Browser checks passed. Screenshots: ${artifacts}`);
} catch (error) {
  screenshot('failure');
  console.error('Last scroll state:', metrics());
  throw error;
} finally {
  browser('close');
}
