import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';

import { privateLiveViewSource } from './sdk-compatibility.mjs';

test('pinned AWS wrapper catches an unavailable display channel asynchronously without destroying the stream', async () => {
  const source = await readFile(new URL('../../../../node_modules/bedrock-agentcore/dist/src/tools/browser/live-view/BrowserLiveView.js', import.meta.url), 'utf8');
  const fixed = privateLiveViewSource(source);
  assert.match(fixed, /Promise\.resolve\(conn\.requestDisplayLayout\?\./);
  assert.match(fixed, /\]\)\)\.catch\(\(\) => \{\}\);/);
  assert.ok(!fixed.includes('dcv.LogLevel.INFO'));
  assert.ok(!fixed.includes('error.message'));
  assert.match(fixed, /baseUrl: new URL\('\/nice-dcv-web-client-sdk\/dcvjs-esm', window.location.origin\).href/);
});

test('an unreviewed SDK revision fails the compatibility build closed', () => {
  assert.throws(() => privateLiveViewSource('export const BrowserLiveView = () => null;'), /Review updated AWS/);
});
