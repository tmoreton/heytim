import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { generateKeyPairSync, createVerify } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import {
  assertInternalOwnerReady,
  inspectAppStoreConnect,
  makeAppStoreConnectToken,
  renderSummary,
} from '../inspect-app-store-connect.mjs';

const { privateKey, publicKey } = generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
const credentials = {
  keyId: 'ABCDEFGHIJ',
  issuerId: '00000000-0000-4000-8000-000000000000',
  privateKey: privateKey.export({ type: 'pkcs8', format: 'pem' }),
  expectedTesterEmail: 'owner@example.invalid',
};

function runOwnerReadyCli(testerState) {
  const responseBodies = [
    { data: [{ type: 'users', attributes: {
      username: 'holder@example.invalid', roles: ['ACCOUNT_HOLDER'],
    } }] },
    { data: [{ type: 'apps', id: '123456789', attributes: { bundleId: 'ai.heytim.app' } }] },
    { data: [], included: [] },
    { data: [{ type: 'betaGroups', id: 'internal-1', attributes: {
      isInternalGroup: true, hasAccessToAllBuilds: true,
    } }] },
    { data: [{ type: 'betaTesters', attributes: {
      email: 'holder@example.invalid', state: testerState,
    } }] },
  ];
  const preload = `data:text/javascript;base64,${Buffer.from(
    `const responses = ${JSON.stringify(responseBodies)};\n`
    + 'globalThis.fetch = async () => ({ ok: true, json: async () => responses.shift() });',
  ).toString('base64')}`;
  const directory = mkdtempSync(join(tmpdir(), 'heytim-owner-ready-'));
  const summaryPath = join(directory, 'summary.md');
  const env = {
    ...process.env,
    APP_STORE_CONNECT_KEY_ID: credentials.keyId,
    APP_STORE_CONNECT_ISSUER_ID: credentials.issuerId,
    APP_STORE_CONNECT_PRIVATE_KEY: credentials.privateKey,
    GITHUB_STEP_SUMMARY: summaryPath,
  };
  delete env.APP_STORE_CONNECT_EXPECTED_INTERNAL_TESTER_EMAIL;
  try {
    const result = spawnSync(process.execPath, [
      '--import', preload,
      new URL('../inspect-app-store-connect.mjs', import.meta.url).pathname,
      '--require-owner-ready',
    ], { env, encoding: 'utf8' });
    return { ...result, summary: readFileSync(summaryPath, 'utf8') };
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

test('signs a short-lived ES256 App Store Connect token', () => {
  const token = makeAppStoreConnectToken(credentials, 1_700_000_000_000);
  const [header, payload, signature] = token.split('.');
  assert.equal(JSON.parse(Buffer.from(header, 'base64url')).alg, 'ES256');
  assert.deepEqual(JSON.parse(Buffer.from(payload, 'base64url')), {
    iss: credentials.issuerId,
    iat: 1_700_000_000,
    exp: 1_700_000_300,
    aud: 'appstoreconnect-v1',
  });
  const verifier = createVerify('SHA256');
  verifier.update(`${header}.${payload}`);
  verifier.end();
  assert.equal(verifier.verify({ key: publicKey, dsaEncoding: 'ieee-p1363' },
    Buffer.from(signature, 'base64url')), true);
});

test('blocks an upload unless the expected owner is accepted in an all-builds internal group', () => {
  assert.doesNotThrow(() => assertInternalOwnerReady({
    ownerInAllBuildsInternalGroup: true, ownerAcceptedOrInstalled: true,
  }));
  assert.throws(() => assertInternalOwnerReady({
    ownerInAllBuildsInternalGroup: true, ownerAcceptedOrInstalled: false,
  }), /not accepted in an internal tester group/);
  assert.throws(() => assertInternalOwnerReady({
    ownerInAllBuildsInternalGroup: false, ownerAcceptedOrInstalled: true,
  }), /not accepted in an internal tester group/);
});

test('upload gate accepts the unique Apple Account Holder without a stored tester email', () => {
  const result = runOwnerReadyCli('ACCEPTED');
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Apple Account Holder in all-builds internal group: yes/);
  assert.match(result.summary, /Apple Account Holder in an all-builds internal group: \*\*yes\*\*/);
  assert.match(result.summary, /Apple Account Holder accepted or installed: \*\*yes\*\*/);
  assert.doesNotMatch(result.summary + result.stdout, /holder@example\.invalid/);
});

test('upload gate still rejects an invited Account Holder', () => {
  const result = runOwnerReadyCli('INVITED');
  assert.equal(result.status, 1);
  assert.match(result.stderr, /not accepted in an internal tester group/);
  assert.doesNotMatch(result.summary + result.stderr, /holder@example\.invalid/);
});

test('requires protected key values before any API call', async () => {
  let called = false;
  await assert.rejects(inspectAppStoreConnect({ ...credentials, privateKey: '' }, () => {
    called = true;
  }), /APP_STORE_CONNECT_PRIVATE_KEY is missing/);
  assert.equal(called, false);
});

test('reports only HeyTim build status and owner membership booleans', async () => {
  const calls = [];
  const privateName = 'Private Person';
  const privateEmail = 'private@example.invalid';
  const responses = [
    { data: [{ type: 'apps', id: '123456789', attributes: { bundleId: 'ai.heytim.app' } }] },
    {
      data: [{
        type: 'builds',
        id: 'opaque-build',
        attributes: {
          version: '20260930123456', uploadedDate: '2026-09-30T12:34:56Z',
          processingState: 'VALID', buildAudienceType: 'INTERNAL_ONLY',
          contactEmail: privateEmail,
        },
        relationships: { preReleaseVersion: { data: { id: 'prerelease-1' } } },
      }],
      included: [{
        type: 'preReleaseVersions', id: 'prerelease-1',
        attributes: { version: '1.0.13', platform: 'IOS' },
      }],
    },
    { data: [{
      type: 'betaGroups', id: 'internal-1', attributes: {
        name: privateName, isInternalGroup: true, hasAccessToAllBuilds: true,
        contactEmail: privateEmail,
      },
    }] },
    { data: [{
      type: 'betaTesters', id: 'private-tester',
      attributes: { email: 'OWNER@example.invalid', state: 'ACCEPTED', firstName: privateName },
    }] },
  ];
  const fetchImpl = async (url, options) => {
    calls.push({ url: String(url), options });
    return { ok: true, json: async () => responses.shift() };
  };
  const inventory = await inspectAppStoreConnect(credentials, fetchImpl);
  const summary = renderSummary(inventory);
  assert.match(summary, /1\.0\.13 \| 20260930123456 \| VALID \| INTERNAL_ONLY/);
  assert.match(summary, /Internal tester group available: \*\*yes\*\*/);
  assert.match(summary, /Expected owner in an all-builds internal group: \*\*yes\*\*/);
  assert.match(summary, /Expected owner accepted or installed: \*\*yes\*\*/);
  assert.doesNotMatch(summary, /Private Person|private@example\.invalid|owner@example\.invalid|opaque-build/);
  assert.equal(calls.length, 4);
  assert.ok(calls.every(call => call.options.method === 'GET'
    && call.url.startsWith('https://api.appstoreconnect.apple.com/v1/')));
  assert.ok(calls[0].url.includes('filter%5BbundleId%5D=ai.heytim.app'));
  assert.ok(calls[1].url.includes('filter%5Bapp%5D=123456789'));
  assert.ok(calls[2].url.includes('fields%5BbetaGroups%5D=isInternalGroup,hasAccessToAllBuilds'));
  assert.ok(calls[3].url.includes('/v1/betaGroups/internal-1/betaTesters'));
});

test('rejects an app identity mismatch before reading builds or groups', async () => {
  let calls = 0;
  const fetchImpl = async () => {
    calls += 1;
    return { ok: true, json: async () => ({
      data: [{ type: 'apps', id: '123456789', attributes: { bundleId: 'other.app' } }],
    }) };
  };
  await assert.rejects(inspectAppStoreConnect(credentials, fetchImpl), /exactly one ai\.heytim\.app app/);
  assert.equal(calls, 1);
});

test('reports processing builds without claiming an unknown audience or marketing version', async () => {
  const responses = [
    { data: [{ type: 'apps', id: '123456789', attributes: { bundleId: 'ai.heytim.app' } }] },
    { data: [{
      type: 'builds', attributes: {
        version: '20260930123456', uploadedDate: '2026-09-30T12:34:56Z',
        processingState: 'PROCESSING', buildAudienceType: null,
      },
    }], included: [] },
    { data: [] },
  ];
  const inventory = await inspectAppStoreConnect(credentials,
    async () => ({ ok: true, json: async () => responses.shift() }));
  assert.match(renderSummary(inventory), /UNKNOWN \| 20260930123456 \| PROCESSING \| UNKNOWN/);
});

test('ignores revoked owner membership and rejects an Apple tester permission error', async () => {
  const firstThree = [
    { data: [{ type: 'apps', id: '123456789', attributes: { bundleId: 'ai.heytim.app' } }] },
    { data: [], included: [] },
    { data: [{ type: 'betaGroups', id: 'internal-1', attributes: {
      isInternalGroup: true, hasAccessToAllBuilds: true,
    } }] },
  ];
  const responses = [
    ...firstThree,
    { data: [{ type: 'betaTesters', attributes: {
      email: 'owner@example.invalid', state: 'REVOKED',
    } }] },
  ];
  const inventory = await inspectAppStoreConnect(credentials,
    async () => ({ ok: true, json: async () => responses.shift() }));
  assert.equal(inventory.ownerInInternalGroup, false);

  const denied = [...firstThree];
  let calls = 0;
  const fetchImpl = async () => {
    calls += 1;
    if (calls === 4) return { ok: false, status: 403 };
    return { ok: true, json: async () => denied.shift() };
  };
  await assert.rejects(inspectAppStoreConnect(credentials, fetchImpl),
    /Apple rejected \/v1\/betaGroups\/internal-1\/betaTesters \(HTTP 403\)/);
});

test('compares the unique Apple Account Holder privately when no expected email is supplied', async () => {
  const responses = [
    { data: [{ type: 'users', attributes: {
      username: 'holder@example.invalid', roles: ['ACCOUNT_HOLDER'],
    } }] },
    { data: [{ type: 'apps', id: '123456789', attributes: { bundleId: 'ai.heytim.app' } }] },
    { data: [], included: [] },
    { data: [{ type: 'betaGroups', id: 'internal-1', attributes: {
      isInternalGroup: true, hasAccessToAllBuilds: true,
    } }] },
    { data: [{ type: 'betaTesters', attributes: {
      email: 'HOLDER@example.invalid', state: 'ACCEPTED',
    } }] },
  ];
  const calls = [];
  const inventory = await inspectAppStoreConnect({
    ...credentials, expectedTesterEmail: undefined,
  }, async url => {
    calls.push(String(url));
    return { ok: true, json: async () => responses.shift() };
  });
  assert.equal(inventory.identitySource, 'Apple Account Holder');
  assert.equal(inventory.ownerInAllBuildsInternalGroup, true);
  assert.doesNotMatch(renderSummary(inventory), /holder@example\.invalid/i);
  assert.ok(calls[0].includes('/v1/users?filter%5Broles%5D=ACCOUNT_HOLDER'));
});
