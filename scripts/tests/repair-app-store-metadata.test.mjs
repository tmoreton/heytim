import assert from 'node:assert/strict';
import { generateKeyPairSync } from 'node:crypto';
import test from 'node:test';

import {
  prepareMetadataRepair,
  renderRepairSummary,
  repairMetadata,
} from '../repair-app-store-metadata.mjs';

const { privateKey } = generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
const credentials = {
  keyId: 'ABCDEFGHIJ',
  issuerId: '00000000-0000-4000-8000-000000000000',
  privateKey: privateKey.export({ type: 'pkcs8', format: 'pem' }),
};

function fixture({ bundleId = 'ai.heytim.app', extraApp = false,
  versionState = 'PREPARE_FOR_SUBMISSION',
  infoState = 'PREPARE_FOR_SUBMISSION' } = {}) {
  const calls = [];
  const info = { type: 'appInfoLocalizations', id: 'info-locale', attributes: {
    locale: 'en-US', name: 'FroggyBot', subtitle: 'Existing subtitle',
    privacyPolicyUrl: 'https://old.example/privacy',
    privacyChoicesUrl: 'https://old.example/choices',
  } };
  const otherInfo = { type: 'appInfoLocalizations', id: 'other-info-locale', attributes: {
    locale: 'en-GB', name: 'Existing other name',
    privacyPolicyUrl: 'https://old.example/privacy',
  } };
  const version = { type: 'appStoreVersionLocalizations', id: 'version-locale', attributes: {
    locale: 'en-US', supportUrl: 'https://old.example/support',
    description: 'Existing description',
  } };
  const otherVersion = { type: 'appStoreVersionLocalizations', id: 'other-version-locale',
    attributes: { locale: 'en-GB', supportUrl: 'https://old.example/support' } };

  async function fetchImpl(url, options) {
    const path = new URL(url).pathname;
    calls.push({ path, method: options.method, body: options.body, url: String(url) });
    if (options.method === 'PATCH') {
      const body = JSON.parse(options.body);
      const resource = path === '/v1/appInfoLocalizations/info-locale' ? info
        : path === '/v1/appStoreVersionLocalizations/version-locale' ? version : null;
      if (!resource) throw new Error(`Unexpected PATCH ${path}`);
      assert.equal(body.data.id, resource.id);
      assert.equal(body.data.type, resource.type);
      Object.assign(resource.attributes, body.data.attributes);
      return { ok: true, status: 200, json: async () => ({ data: resource }) };
    }
    assert.equal(options.method, 'GET');
    let data;
    if (path === '/v1/apps') {
      data = [{ type: 'apps', id: 'app-123', attributes: {
        bundleId, primaryLocale: 'en-US',
      } }];
      if (extraApp) data.push({
        type: 'apps', id: 'foreign-app', attributes: {
          bundleId: 'ai.other.app', primaryLocale: 'en-US',
        },
      });
    } else if (path === '/v1/apps/app-123/appInfos') {
      data = [{ type: 'appInfos', id: 'info-123', attributes: { state: infoState } }];
    } else if (path === '/v1/apps/app-123/appStoreVersions') {
      data = [{ type: 'appStoreVersions', id: 'store-version', attributes: {
        platform: 'IOS', versionString: '1.0.13', appStoreState: versionState,
      } }];
    } else if (path === '/v1/appInfos/info-123/appInfoLocalizations') {
      data = [info, otherInfo];
    } else if (path === '/v1/appStoreVersions/store-version/appStoreVersionLocalizations') {
      data = [version, otherVersion];
    } else if (path === '/v1/appInfoLocalizations/info-locale') data = info;
    else if (path === '/v1/appStoreVersionLocalizations/version-locale') data = version;
    else throw new Error(`Unexpected GET ${path}`);
    return { ok: true, status: 200, json: async () => ({ data }) };
  }
  return { calls, info, otherInfo, version, otherVersion, fetchImpl };
}

test('dry run proposes only three primary-locale fields and never writes', async () => {
  const api = fixture();
  const plan = await repairMetadata(credentials, '1.0.13', {}, api.fetchImpl);
  assert.equal(plan.applied, false);
  assert.deepEqual(plan.changes, {
    appInfo: { name: 'HeyTim', privacyPolicyUrl: 'https://heytim.ai/privacy/' },
    iosVersion: { supportUrl: 'https://heytim.ai/support/' },
  });
  assert.match(plan.fingerprint, /^[a-f0-9]{64}$/);
  assert.equal(api.calls.length, 5);
  assert.ok(api.calls.every(call => call.method === 'GET'
    && call.url.startsWith('https://api.appstoreconnect.apple.com/v1/')));
  const summary = renderRepairSummary(plan);
  assert.match(summary, /name, privacyPolicyUrl, supportUrl/);
  assert.doesNotMatch(summary, /FroggyBot|old\.example|info-locale/);
});

test('apply accepts only the exact fresh fingerprint and sends minimal PATCH bodies', async () => {
  const api = fixture();
  const plan = await prepareMetadataRepair(credentials, '1.0.13', api.fetchImpl);
  const result = await repairMetadata(credentials, '1.0.13', {
    apply: true, expectedPlanHash: plan.fingerprint,
  }, api.fetchImpl);
  assert.equal(result.applied, true);
  const patches = api.calls.filter(call => call.method === 'PATCH');
  assert.equal(patches.length, 2);
  assert.deepEqual(JSON.parse(patches[0].body), { data: {
    type: 'appInfoLocalizations', id: 'info-locale', attributes: {
      name: 'HeyTim', privacyPolicyUrl: 'https://heytim.ai/privacy/',
    },
  } });
  assert.deepEqual(JSON.parse(patches[1].body), { data: {
    type: 'appStoreVersionLocalizations', id: 'version-locale',
    attributes: { supportUrl: 'https://heytim.ai/support/' },
  } });
  assert.equal(api.info.attributes.subtitle, 'Existing subtitle');
  assert.equal(api.info.attributes.privacyChoicesUrl, 'https://old.example/choices');
  assert.equal(api.version.attributes.description, 'Existing description');
  assert.equal(api.otherInfo.attributes.name, 'Existing other name');
  assert.equal(api.otherVersion.attributes.supportUrl, 'https://old.example/support');
  assert.equal(api.calls.filter(call => call.method === 'GET').length, 12);
});

test('apply stops before writing if listing changes after preview', async () => {
  const api = fixture();
  const plan = await prepareMetadataRepair(credentials, '1.0.13', api.fetchImpl);
  api.info.attributes.name = 'Changed after preview';
  await assert.rejects(repairMetadata(credentials, '1.0.13', {
    apply: true, expectedPlanHash: plan.fingerprint,
  }, api.fetchImpl), /differs from the reviewed dry run/);
  assert.equal(api.calls.filter(call => call.method === 'PATCH').length, 0);
});

test('requires exact bundle ID, editable iOS draft, and a valid version', async () => {
  await assert.rejects(prepareMetadataRepair(credentials, '1.0.13',
    fixture({ bundleId: 'ai.other.app' }).fetchImpl), /did not resolve ai\.heytim\.app/);
  await assert.rejects(prepareMetadataRepair(credentials, '1.0.13',
    fixture({ extraApp: true }).fetchImpl), /exactly one ai\.heytim\.app app/);
  await assert.rejects(prepareMetadataRepair(credentials, '1.0.13',
    fixture({ versionState: 'READY_FOR_SALE' }).fetchImpl),
  /exactly one editable iOS 1\.0\.13 App Store version/);
  await assert.rejects(prepareMetadataRepair(credentials, '1.0.13-beta',
    fixture().fetchImpl), /MAJOR\.MINOR\.PATCH/);
});

test('a single current app info is eligible only alongside an editable iOS draft', async () => {
  const api = fixture({ infoState: 'READY_FOR_SALE' });
  const plan = await prepareMetadataRepair(credentials, '1.0.13', api.fetchImpl);
  assert.equal(plan.appInfoState, 'READY_FOR_SALE');
  assert.equal(api.calls.filter(call => call.method === 'PATCH').length, 0);
});
