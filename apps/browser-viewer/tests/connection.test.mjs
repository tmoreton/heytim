import assert from 'node:assert/strict';
import { test } from 'node:test';
import { connectLiveView, validSession } from '../src/connection.ts';

const signedUrl = 'https://bedrock-agentcore.us-east-1.amazonaws.com/browser-streams/aws.browser.v1/sessions/test-session/live-view?X-Amz-Signature=' + 'a'.repeat(64) + '&X-Amz-Expires=300';
const session = { signedUrl, width: 1440, height: 900 };
const flush = () => new Promise(setImmediate);
function fixture() {
  const phases = [], layouts = [];
  let auth, config, disconnects = 0, connections = 0;
  const sdk = {
    setLogHandler() {},
    authenticate(_url, callbacks) { auth = callbacks; },
    async connect(value) {
      config = value;
      connections += 1;
      return { disconnect() { disconnects += 1; config.observers.disconnect(); } };
    },
  };
  return {
    sdk, phases, layouts,
    start(timeout = 20000) {
      return connectLiveView(sdk, session, 'test-display', 'https://heytim.ai',
        phase => phases.push(phase), (...layout) => layouts.push(layout), timeout);
    },
    authenticate() { auth.success({}, [{ sessionId: 'session', authToken: 'test-token' }]); },
    get auth() { return auth; }, get config() { return config; },
    get disconnects() { return disconnects; }, get connections() { return connections; },
  };
}

test('accepts the signed AWS stream and rejects unrelated or malformed capabilities', () => {
  assert.deepEqual(validSession(signedUrl, 1440, 900), session);
  for (const invalid of [
    signedUrl.replace('https:', 'http:'), signedUrl.replace('amazonaws.com', 'amazonaws.com.attacker.test'),
    signedUrl.replace('/live-view?', '/live-view/extra?'), signedUrl.replace('=300', '=301'),
    signedUrl.replace('=300', '=0'), signedUrl.replace('=300', '=1.5'),
    signedUrl.replace('a'.repeat(64), 'invalid'), signedUrl.replace('https://', 'https://user:secret@'),
    signedUrl.replace('amazonaws.com/', 'amazonaws.com:8443/'), 'not-a-url',
  ]) assert.equal(validSession(invalid, 1440, 900), null);
  for (const [width, height] of [[0, 900], [1440, NaN], [390.5, 780], [4000, 900], [390, 3000]]) {
    assert.equal(validSession(signedUrl, width, height), null);
  }
});

test('only the first frame confirms a usable stream, with signed query and absolute decoder path', async () => {
  const f = fixture(), dispose = f.start();
  f.authenticate(); await flush();
  assert.deepEqual(f.phases, ['connecting']);
  assert.equal(f.config.baseUrl, 'https://heytim.ai/nice-dcv-web-client-sdk/dcvjs-esm');
  assert.equal(f.config.clipboardAutoSync, false);
  assert.equal(f.auth.httpExtraSearchParams().toString(), new URL(signedUrl).searchParams.toString());
  assert.equal(f.config.observers.httpExtraSearchParams().toString(), f.auth.httpExtraSearchParams().toString());
  f.config.observers.firstFrame();
  assert.deepEqual(f.phases, ['connecting', 'connected']);
  dispose(); assert.equal(f.disconnects, 1);
});

for (const failure of ['error', 'promptCredentials', 'emptyCredentials']) {
  test('authentication ' + failure + ' produces an actionable failure', () => {
    const f = fixture(), dispose = f.start();
    if (failure === 'emptyCredentials') f.auth.success({}, [{}]);
    else f.auth[failure]({}, { message: signedUrl });
    assert.deepEqual(f.phases, ['connecting', 'failed']);
    f.authenticate(); assert.equal(f.connections, 0);
    dispose();
  });
}

for (const stage of ['authenticate', 'connect-sync', 'connect-async']) {
  test('handles ' + stage + ' exceptions without exposing provider details', async () => {
    const f = fixture();
    if (stage === 'authenticate') f.sdk.authenticate = () => { throw new Error(signedUrl); };
    if (stage === 'connect-sync') f.sdk.connect = () => { throw new Error(signedUrl); };
    if (stage === 'connect-async') f.sdk.connect = async () => { throw new Error(signedUrl); };
    const dispose = f.start();
    if (stage !== 'authenticate') f.authenticate();
    await flush();
    assert.deepEqual(f.phases, ['connecting', 'failed']);
    dispose();
  });
}

test('disconnect after a frame clears the live state and cleans up once', async () => {
  const f = fixture(), dispose = f.start();
  f.authenticate(); await flush(); f.config.observers.firstFrame();
  f.config.observers.disconnect(); f.config.observers.disconnect();
  assert.deepEqual(f.phases, ['connecting', 'connected', 'disconnected']);
  dispose(); assert.equal(f.disconnects, 1);
});

test('bounds both authentication and first-frame waits', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  for (const authenticate of [false, true]) {
    const f = fixture(), dispose = f.start(100);
    if (authenticate) { f.authenticate(); await flush(); }
    t.mock.timers.tick(100);
    assert.deepEqual(f.phases, ['connecting', 'timeout']);
    f.authenticate(); f.config?.observers.firstFrame();
    assert.equal(f.phases.at(-1), 'timeout');
    dispose();
  }
});

test('a received frame cancels the startup timeout', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const f = fixture(), dispose = f.start(100);
  f.authenticate(); await flush(); f.config.observers.firstFrame();
  t.mock.timers.tick(1000);
  assert.deepEqual(f.phases, ['connecting', 'connected']);
  dispose();
});

test('closing while authentication is pending prevents a late connection', () => {
  const f = fixture(), dispose = f.start();
  dispose(); f.authenticate();
  assert.equal(f.connections, 0);
  assert.deepEqual(f.phases, ['connecting']);
});

test('closing during connect disconnects the late result and ignores stale observers', async () => {
  const f = fixture(); let complete, disconnects = 0;
  f.sdk.connect = config => {
    return new Promise(resolve => { complete = resolve; });
  };
  const dispose = f.start(); f.authenticate(); dispose();
  complete({ disconnect() { disconnects += 1; } }); await flush();
  assert.equal(disconnects, 1);
  assert.deepEqual(f.phases, ['connecting']);
});

test('duplicate authentication callbacks do not open two connections', async () => {
  const f = fixture(), dispose = f.start();
  f.authenticate(); f.authenticate(); await flush();
  assert.equal(f.connections, 1); dispose();
});

test('remote layouts update fitting only for valid dimensions', async () => {
  const f = fixture(), dispose = f.start();
  f.authenticate(); await flush();
  for (const values of [[390, 780], [0, 10], [NaN, 900], [10000, 900]]) {
    f.config.observers.displayLayout(...values);
  }
  assert.deepEqual(f.layouts, [[390, 780]]);
  dispose(); f.config.observers.displayLayout(1440, 900);
  assert.equal(f.layouts.length, 1);
});

test('twenty open/frame/close cycles release every connection', async () => {
  const f = fixture();
  for (let cycle = 0; cycle < 20; cycle += 1) {
    const dispose = f.start(); f.authenticate(); await flush();
    f.config.observers.firstFrame(); dispose(); dispose();
  }
  assert.equal(f.connections, 20); assert.equal(f.disconnects, 20);
  assert.equal(f.phases.filter(phase => phase === 'connected').length, 20);
});
