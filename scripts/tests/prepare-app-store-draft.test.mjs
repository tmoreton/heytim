import assert from 'node:assert/strict';
import { generateKeyPairSync } from 'node:crypto';
import test from 'node:test';

import {
  planAppStoreDraft,
  prepareAppStoreDraft,
  renderDraftSummary,
} from '../prepare-app-store-draft.mjs';

const { privateKey } = generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
const credentials = {
  keyId: 'ABCDEFGHIJ',
  issuerId: '00000000-0000-4000-8000-000000000000',
  privateKey: privateKey.export({ type: 'pkcs8', format: 'pem' }),
};

function fixture({ bundleId = 'ai.heytim.app', draft = false,
  primaryLocalization = false, otherDraft = false, failLocalizationOnce = false } = {}) {
  const calls = [];
  let failNextLocalization = failLocalizationOnce;
  const versions = [{ type: 'appStoreVersions', id: 'old-version', attributes: {
    platform: 'IOS', versionString: '1.0.12', appStoreState: 'READY_FOR_SALE',
  } }];
  if (otherDraft) versions.push({ type: 'appStoreVersions', id: 'other-draft', attributes: {
    platform: 'IOS', versionString: '1.0.14', appStoreState: 'PREPARE_FOR_SUBMISSION',
  } });
  if (draft) versions.push({ type: 'appStoreVersions', id: 'new-version', attributes: {
    platform: 'IOS', versionString: '1.0.13', appStoreState: 'PREPARE_FOR_SUBMISSION',
    releaseType: 'MANUAL',
  } });
  const localizations = primaryLocalization
    ? [{ type: 'appStoreVersionLocalizations', id: 'primary-locale', attributes: {
      locale: 'en-US', supportUrl: 'https://old.example/support',
      description: 'Existing description',
    } }]
    : [];

  async function fetchImpl(url, options) {
    const path = new URL(url).pathname;
    calls.push({ path, method: options.method, body: options.body, url: String(url) });
    if (options.method === 'POST') {
      const body = JSON.parse(options.body);
      if (path === '/v1/appStoreVersions') {
        assert.deepEqual(body, { data: {
          type: 'appStoreVersions', attributes: {
            platform: 'IOS', versionString: '1.0.13', releaseType: 'MANUAL',
          }, relationships: { app: { data: { type: 'apps', id: 'app-123' } } },
        } });
        const created = { type: 'appStoreVersions', id: 'new-version', attributes: {
          ...body.data.attributes, appStoreState: 'PREPARE_FOR_SUBMISSION',
        } };
        versions.push(created);
        return { ok: true, status: 201, json: async () => ({ data: created }) };
      }
      if (path === '/v1/appStoreVersionLocalizations') {
        if (failNextLocalization) {
          failNextLocalization = false;
          return { ok: false, status: 409 };
        }
        assert.deepEqual(body, { data: {
          type: 'appStoreVersionLocalizations', attributes: {
            locale: 'en-US', supportUrl: 'https://heytim.ai/support/',
          }, relationships: { appStoreVersion: {
            data: { type: 'appStoreVersions', id: 'new-version' },
          } },
        } });
        const created = { type: 'appStoreVersionLocalizations', id: 'primary-locale',
          attributes: body.data.attributes };
        localizations.push(created);
        return { ok: true, status: 201, json: async () => ({ data: created }) };
      }
      throw new Error(`Unexpected POST ${path}`);
    }
    assert.equal(options.method, 'GET');
    let data;
    if (path === '/v1/apps') data = [{ type: 'apps', id: 'app-123', attributes: {
      bundleId, primaryLocale: 'en-US',
    } }];
    else if (path === '/v1/apps/app-123/appInfos') data = [{
      type: 'appInfos', id: 'info-123', attributes: { state: 'READY_FOR_SALE' },
    }];
    else if (path === '/v1/appInfos/info-123/appInfoLocalizations') data = [{
      type: 'appInfoLocalizations', id: 'info-locale', attributes: { locale: 'en-US' },
    }];
    else if (path === '/v1/apps/app-123/appStoreVersions') data = versions;
    else if (path === '/v1/appStoreVersions/new-version') {
      data = versions.find(item => item.id === 'new-version');
    } else if (path === '/v1/appStoreVersions/new-version/appStoreVersionLocalizations') {
      data = localizations;
    } else throw new Error(`Unexpected GET ${path}`);
    return { ok: true, status: 200, json: async () => ({ data }) };
  }
  return { calls, versions, localizations, fetchImpl };
}

test('plan is read-only and targets exactly the HeyTim iOS 1.0.13 draft', async () => {
  const api = fixture();
  const result = await prepareAppStoreDraft(credentials, '1.0.13', {}, api.fetchImpl);
  assert.equal(result.applied, false);
  assert.equal(result.createVersion, true);
  assert.equal(result.createPrimaryLocalization, true);
  assert.match(result.fingerprint, /^[a-f0-9]{64}$/);
  assert.ok(api.calls.every(call => call.method === 'GET'
    && call.url.startsWith('https://api.appstoreconnect.apple.com/v1/')));
  assert.match(renderDraftSummary(result), /PREPARE_FOR_SUBMISSION/);
});

test('apply creates a manual-release draft and only the missing primary locale', async () => {
  const api = fixture();
  const plan = await planAppStoreDraft(credentials, '1.0.13', api.fetchImpl);
  const result = await prepareAppStoreDraft(credentials, '1.0.13', {
    apply: true, expectedPlanHash: plan.fingerprint,
  }, api.fetchImpl);
  assert.equal(result.versionCreated, true);
  assert.equal(result.localizationCreated, true);
  assert.equal(result.versionId, 'new-version');
  assert.equal(result.primaryLocalizationId, 'primary-locale');
  assert.deepEqual(api.calls.filter(call => call.method === 'POST').map(call => call.path), [
    '/v1/appStoreVersions', '/v1/appStoreVersionLocalizations',
  ]);
  assert.equal(api.versions[0].attributes.versionString, '1.0.12');
  assert.equal(api.localizations[0].attributes.supportUrl, 'https://heytim.ai/support/');
});

test('existing editable version is idempotent and preserves its localization text', async () => {
  const api = fixture({ draft: true, primaryLocalization: true });
  const plan = await planAppStoreDraft(credentials, '1.0.13', api.fetchImpl);
  const result = await prepareAppStoreDraft(credentials, '1.0.13', {
    apply: true, expectedPlanHash: plan.fingerprint,
  }, api.fetchImpl);
  assert.equal(result.versionCreated, false);
  assert.equal(result.localizationCreated, false);
  assert.equal(api.localizations[0].attributes.description, 'Existing description');
  assert.equal(api.calls.filter(call => call.method === 'POST').length, 0);
});

test('a failed localization creation can be resumed after a fresh plan', async () => {
  const api = fixture({ failLocalizationOnce: true });
  const initialPlan = await planAppStoreDraft(credentials, '1.0.13', api.fetchImpl);
  await assert.rejects(prepareAppStoreDraft(credentials, '1.0.13', {
    apply: true, expectedPlanHash: initialPlan.fingerprint,
  }, api.fetchImpl), /rejected appStoreVersionLocalizations creation/);
  const resumePlan = await planAppStoreDraft(credentials, '1.0.13', api.fetchImpl);
  assert.equal(resumePlan.createVersion, false);
  assert.notEqual(initialPlan.fingerprint, resumePlan.fingerprint);
  const result = await prepareAppStoreDraft(credentials, '1.0.13', {
    apply: true, expectedPlanHash: resumePlan.fingerprint,
  }, api.fetchImpl);
  assert.equal(result.versionCreated, false);
  assert.equal(result.localizationCreated, true);
  assert.equal(api.calls.filter(call => call.path === '/v1/appStoreVersions'
    && call.method === 'POST').length, 1);
});

test('stale plan, wrong app, and another editable iOS version prevent writes', async () => {
  const api = fixture();
  const plan = await planAppStoreDraft(credentials, '1.0.13', api.fetchImpl);
  api.versions[0].attributes.versionString = '1.0.11';
  await assert.rejects(prepareAppStoreDraft(credentials, '1.0.13', {
    apply: true, expectedPlanHash: plan.fingerprint,
  }, api.fetchImpl), /differs from the reviewed plan/);
  assert.equal(api.calls.filter(call => call.method === 'POST').length, 0);
  api.versions.push({ type: 'appStoreVersions', id: 'other-draft', attributes: {
    platform: 'IOS', versionString: '1.0.14', appStoreState: 'PREPARE_FOR_SUBMISSION',
  } });
  await assert.rejects(prepareAppStoreDraft(credentials, '1.0.13', {
    apply: true, expectedPlanHash: plan.fingerprint,
  }, api.fetchImpl), /Another editable iOS App Store version/);
  assert.equal(api.calls.filter(call => call.method === 'POST').length, 0);
  await assert.rejects(planAppStoreDraft(credentials, '1.0.13',
    fixture({ bundleId: 'ai.other.app' }).fetchImpl), /did not resolve ai\.heytim\.app/);
  await assert.rejects(planAppStoreDraft(credentials, '1.0.13',
    fixture({ otherDraft: true }).fetchImpl), /Another editable iOS App Store version/);
  await assert.rejects(planAppStoreDraft(credentials, '1.0.13',
    fixture({ draft: true, otherDraft: true }).fetchImpl), /Another editable iOS App Store version/);
  await assert.rejects(planAppStoreDraft(credentials, '1.0.13-beta',
    fixture().fetchImpl), /MAJOR\.MINOR\.PATCH/);
});
