import assert from 'node:assert/strict';
import { generateKeyPairSync } from 'node:crypto';
import test from 'node:test';

import {
  inspectAppStoreMetadata,
  renderMetadataSummary,
} from '../inspect-app-store-metadata.mjs';

const { privateKey } = generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
const credentials = {
  keyId: 'ABCDEFGHIJ',
  issuerId: '00000000-0000-4000-8000-000000000000',
  privateKey: privateKey.export({ type: 'pkcs8', format: 'pem' }),
};

test('checks Apple listing links with read-only requests and omits raw metadata from summary', async () => {
  const calls = [];
  const responses = [
    { data: [{ type: 'apps', id: '123456789', attributes: {
      bundleId: 'ai.heytim.app', primaryLocale: 'en-US',
    } }] },
    { data: [{ type: 'appInfos', id: 'info-1', attributes: {
      state: 'READY_FOR_SALE',
    } }] },
    { data: [{ type: 'appInfoLocalizations', id: 'locale-1', attributes: {
      locale: 'en-US', name: 'HeyTim',
      privacyPolicyUrl: 'https://heytim.ai/privacy/',
      privacyChoicesUrl: 'https://heytim.ai/account-deletion/',
    } }] },
    { data: [{ type: 'appStoreVersions', id: 'version-1', attributes: {
      platform: 'IOS', versionString: '1.0.13', appStoreState: 'PREPARE_FOR_SUBMISSION',
    } }] },
    { data: [{ type: 'appStoreVersionLocalizations', id: 'version-locale-1', attributes: {
      locale: 'en-US', supportUrl: 'https://heytim.ai/support/',
    } }] },
  ];
  const inventory = await inspectAppStoreMetadata(credentials, async (url, options) => {
    calls.push({ url: String(url), options });
    return { ok: true, json: async () => responses.shift() };
  });
  assert.deepEqual(inventory.appInfos[0].localizations[0], {
    locale: 'en-US', heytimName: true, privacyPolicy: true, privacyChoices: true,
  });
  assert.deepEqual(inventory.iosVersions[0].localizations[0], {
    locale: 'en-US', support: true,
  });
  assert.equal(calls.length, 5);
  assert.ok(calls.every(call => call.options.method === 'GET'
    && call.url.startsWith('https://api.appstoreconnect.apple.com/v1/')));
  const summary = renderMetadataSummary(inventory);
  assert.match(summary, /READY_FOR_SALE \| en-US \| yes \| yes \| yes/);
  assert.match(summary, /1\.0\.13 \| PREPARE_FOR_SUBMISSION \| en-US \| yes/);
  assert.doesNotMatch(summary, /https:\/\/heytim\.ai/);
});

test('reports missing Apple metadata without assuming TestFlight metadata exists', async () => {
  const responses = [
    { data: [{ type: 'apps', id: '123456789', attributes: {
      bundleId: 'ai.heytim.app', primaryLocale: 'en-US',
    } }] },
    { data: [] },
    { data: [] },
  ];
  const inventory = await inspectAppStoreMetadata(credentials,
    async () => ({ ok: true, json: async () => responses.shift() }));
  assert.match(renderMetadataSummary(inventory), /No app info localization/);
  assert.match(renderMetadataSummary(inventory), /No iOS App Store version localization/);
});

test('rejects incomplete Apple listing pages instead of reporting a partial pass', async () => {
  const responses = [
    { data: [{ type: 'apps', id: '123456789', attributes: {
      bundleId: 'ai.heytim.app', primaryLocale: 'en-US',
    } }] },
    { data: [], links: { next: 'https://api.appstoreconnect.apple.com/v1/next-page' } },
  ];
  await assert.rejects(inspectAppStoreMetadata(credentials,
    async () => ({ ok: true, json: async () => responses.shift() })),
  /incomplete appInfos list/);
});

test('does not treat a foreign or insecure URL as HeyTim metadata', async () => {
  const responses = [
    { data: [{ type: 'apps', id: '123456789', attributes: {
      bundleId: 'ai.heytim.app', primaryLocale: 'en-US',
    } }] },
    { data: [{ type: 'appInfos', id: 'info-1', attributes: { state: 'READY_FOR_SALE' } }] },
    { data: [{ type: 'appInfoLocalizations', id: 'locale-1', attributes: {
      locale: 'en-US', name: 'HeyTim',
      privacyPolicyUrl: 'http://heytim.ai/privacy/',
      privacyChoicesUrl: 'https://other.example/account-deletion/',
    } }] },
    { data: [] },
  ];
  const inventory = await inspectAppStoreMetadata(credentials,
    async () => ({ ok: true, json: async () => responses.shift() }));
  assert.deepEqual(inventory.appInfos[0].localizations[0], {
    locale: 'en-US', heytimName: true, privacyPolicy: false, privacyChoices: false,
  });
});
