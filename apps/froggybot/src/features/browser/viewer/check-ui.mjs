import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

// Run serve-fixture.mjs first. This exercises the real UI with an explicit fake
// API/viewer; no AWS request, token, bot turn, or website submission is involved.
const executable = process.env.AGENT_BROWSER_BIN ?? execFileSync('npm', ['exec', '--yes', '--package=agent-browser@0.27.0', '--', 'which', 'agent-browser'], { encoding: 'utf8' }).trim();
const session = `frogbot-browser-handoff-${process.pid}`;
const evidence = mkdtempSync(join(tmpdir(), 'frogbot-browser-handoff-'));
const browser = (...args) => {
  const result = JSON.parse(execFileSync(executable, ['--session', session, '--json', ...args], { encoding: 'utf8', timeout: 60_000, maxBuffer: 4 * 1024 * 1024 }));
  assert.equal(result.success, true, result.error);
  return result.data;
};
const snapshot = () => browser('snapshot', '-i');
const evaluate = (source) => browser('eval', source).result;
const click = (name) => { snapshot(); browser('find', 'role', 'button', 'click', '--name', name, '--exact'); };
const counters = () => JSON.parse(evaluate('document.getElementById("counters").textContent'));
const text = () => evaluate('document.body.innerText');
const reset = (scenario = 'normal') => {
  browser('open', 'http://127.0.0.1:8917');
  snapshot();
  browser('select', '[aria-label="Scenario"]', scenario);
};
try {
  reset();
  click('Open bot browser');
  browser('wait', 'iframe');
  assert.equal(counters().opens, 1);
  click('Browser options');
  assert.equal(evaluate('document.querySelector("[role=switch]").checked'), false);
  click('Browser options');
  assert.ok(!evaluate('document.querySelector("iframe").src').includes('Signature'));
  assert.ok(!text().includes('TEST-ONLY-NOT-A-CREDENTIAL'));
  browser('screenshot', join(evidence, 'desktop-human-control.png'));
  for (const width of [390, 320]) {
    browser('set', 'viewport', String(width), '844');
    snapshot();
    assert.ok(evaluate('document.documentElement.scrollWidth <= innerWidth'));
    assert.ok(evaluate('Array.from(document.querySelectorAll("[role=button]")).find(e => e.textContent === "Resume bot").getBoundingClientRect().bottom <= innerHeight'));
    browser('screenshot', join(evidence, `mobile-${width}.png`));
  }
  click('Resume bot');
  assert.equal(counters().resumes, 1);
  assert.equal(counters().refreshed, 1);
  assert.equal(counters().consent, false);
  assert.equal(evaluate('Boolean(document.querySelector("iframe"))'), false);
  console.log('PASS: direct handoff, default no-save consent, private iframe URL, responsive controls, conversation refresh.');

  reset('busy'); click('Open bot browser');
  assert.match(text(), /busy.*Wait/s);
  assert.equal(counters().opens, 1);
  assert.equal(evaluate('Boolean(document.querySelector("iframe"))'), false);
  console.log('PASS: active-run conflict surfaces guidance and does not retry.');

  reset('expiry'); click('Open bot browser');
  browser('wait', '1800');
  assert.match(text(), /viewing connection expired/);
  assert.equal(evaluate('Boolean(document.querySelector("iframe"))'), false);
  click('Refresh connection');
  assert.equal(counters().opens, 2);
  console.log('PASS: expiry discards the viewer; explicit Refresh gets a new capability.');

  reset('saving'); click('Open bot browser'); click('Browser options');
  snapshot(); browser('find', 'role', 'switch', 'click', '--name', 'Remember login for this bot only');
  click('Resume bot');
  assert.match(text(), /Saving your private profile/);
  assert.equal(counters().refreshed, 0, 'Pending profile save must not close the modal or claim a resumed turn.');
  browser('wait', '5000');
  assert.equal(counters().resumes, 3);
  assert.equal(counters().consent, true);
  assert.equal(counters().refreshed, 1);
  console.log('PASS: acknowledged profile save polls with consent and closes only after a ready turn.');

  reset('uncertain'); click('Open bot browser'); click('Resume bot');
  browser('wait', '2300');
  assert.equal(counters().resumes, 1);
  assert.equal(counters().refreshed, 0);
  assert.match(text(), /Could not confirm the handoff/);
  console.log('PASS: uncertain resume never retries automatically or claims success.');

  reset(); click('Remove browser capability'); click('Browser connection');
  assert.match(text(), /browser tool is no longer enabled/);
  click('Browser options');
  click('Forget login');
  assert.equal(counters().forgets, 0);
  click('Cancel');
  assert.equal(counters().forgets, 0);
  click('Forget login'); click('Forget login');
  assert.equal(counters().forgets, 1);
  assert.match(text(), /No saved login/);
  console.log('PASS: removed browser capability retains cleanup access, with explicit confirmation.');

  reset(); browser('set', 'viewport', '390', '844');
  snapshot(); browser('find', 'role', 'link', 'click', '--name', 'Open example');
  browser('wait', 'iframe');
  assert.equal(counters().opens, 1);
  assert.equal(counters().url, 'https://example.com/chat-link');
  assert.equal(counters().display, 'mobile');
  click('Browser options'); click('Request desktop site');
  assert.equal(counters().display, 'desktop');
  assert.equal(counters().url, '', 'Changing display or refreshing must not repeat navigation.');
  console.log('PASS: real markdown links open the same bot browser in mobile mode; display override does not replay navigation.');

  reset('active');
  snapshot(); browser('find', 'role', 'link', 'click', '--name', 'Open example');
  assert.equal(counters().opens, 0, 'Opening a link must not interrupt an active bot.');
  browser('wait', '1800');
  click('Open browser');
  assert.equal(counters().url, 'https://example.com/chat-link', 'Keep the clicked link for the first manual open after the bot finishes.');
  assert.equal(counters().opens, 1);
  console.log('PASS: an active bot is not interrupted and its clicked link is retained.');

  assert.deepEqual(browser('errors').errors, []);
  console.log(`UI evidence: ${evidence}`);
} finally { browser('close'); }
