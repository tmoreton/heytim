import assert from 'node:assert/strict';
import { generateKeyPairSync, createVerify } from 'node:crypto';
import test from 'node:test';

import {
  inspectAppStoreConnect,
  makeAppStoreConnectToken,
  renderSummary,
} from '../inspect-app-store-connect.mjs';

const { privateKey, publicKey } = generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
const credentials = {
  keyId: 'ABCDEFGHIJ',
  issuerId: '00000000-0000-4000-8000-000000000000',
  privateKey: privateKey.export({ type: 'pkcs8', format: 'pem' }),
};

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

test('requires protected key values before any API call', async () => {
  let called = false;
  await assert.rejects(inspectAppStoreConnect({ ...credentials, privateKey: '' }, () => {
    called = true;
  }), /APP_STORE_CONNECT_PRIVATE_KEY is missing/);
  assert.equal(called, false);
});

test('reports only HeyTim build status and internal group availability', async () => {
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
      type: 'betaGroups', attributes: {
        name: privateName, isInternalGroup: true, hasAccessToAllBuilds: true,
        contactEmail: privateEmail,
      },
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
  assert.doesNotMatch(summary, /Private Person|private@example\.invalid|opaque-build/);
  assert.equal(calls.length, 3);
  assert.ok(calls.every(call => call.options.method === 'GET'
    && call.url.startsWith('https://api.appstoreconnect.apple.com/v1/')));
  assert.ok(calls[0].url.includes('filter%5BbundleId%5D=ai.heytim.app'));
  assert.ok(calls[1].url.includes('filter%5Bapp%5D=123456789'));
  assert.ok(calls[2].url.includes('fields%5BbetaGroups%5D=isInternalGroup,hasAccessToAllBuilds'));
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
