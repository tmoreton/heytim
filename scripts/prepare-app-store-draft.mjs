#!/usr/bin/env node

import { createHash } from 'node:crypto';
import { appendFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

import { getJson, makeAppStoreConnectToken } from './inspect-app-store-connect.mjs';

const ORIGIN = 'https://api.appstoreconnect.apple.com';
const BUNDLE_ID = 'ai.heytim.app';
const VERSION = /^\d+\.\d+\.\d+$/;
const ID = /^[A-Za-z0-9-]{1,128}$/;
const LOCALE = /^[a-z]{2,3}(?:-[A-Z0-9]{2,8})*$/;
const DRAFT_STATE = 'PREPARE_FOR_SUBMISSION';
const SUPPORT_URL = 'https://heytim.ai/support/';

function list(response, type) {
  if (!Array.isArray(response.data) || response.links?.next
    || response.data.some(item => item?.type !== type || !ID.test(item.id))) {
    throw new Error(`Apple returned an incomplete or invalid ${type} list for HeyTim.`);
  }
  return response.data;
}

function one(items, label) {
  if (items.length !== 1) {
    throw new Error(`Expected exactly one ${label}; found ${items.length}. No draft created.`);
  }
  return items[0];
}

function validLocale(value) {
  if (typeof value !== 'string' || !LOCALE.test(value)) {
    throw new Error('Apple returned an invalid HeyTim primary locale.');
  }
  return value;
}

function versionInventory(versions) {
  return versions.map(version => ({
    id: version.id,
    platform: version.attributes?.platform,
    version: version.attributes?.versionString,
    state: version.attributes?.appStoreState,
  })).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
}

async function localizations(versionId, token, fetchImpl) {
  return list(await getJson(
    `/v1/appStoreVersions/${versionId}/appStoreVersionLocalizations`
      + '?fields%5BappStoreVersionLocalizations%5D=locale,supportUrl&limit=200',
    token, fetchImpl,
  ), 'appStoreVersionLocalizations');
}

export async function planAppStoreDraft(credentials, marketingVersion, fetchImpl = fetch) {
  if (!VERSION.test(marketingVersion)) {
    throw new Error('The target iOS App Store version must be MAJOR.MINOR.PATCH.');
  }
  const token = makeAppStoreConnectToken(credentials);
  const apps = list(await getJson(
    `/v1/apps?filter%5BbundleId%5D=${encodeURIComponent(BUNDLE_ID)}`
      + '&fields%5Bapps%5D=bundleId,primaryLocale&limit=2', token, fetchImpl,
  ), 'apps');
  const app = one(apps, `${BUNDLE_ID} app`);
  if (app.attributes?.bundleId !== BUNDLE_ID) {
    throw new Error(`The API key did not resolve ${BUNDLE_ID}. No draft created.`);
  }
  const primaryLocale = validLocale(app.attributes?.primaryLocale);

  // The following app info checks are the same prerequisite as the metadata repair.
  const infos = list(await getJson(
    `/v1/apps/${app.id}/appInfos?fields%5BappInfos%5D=state&limit=200`,
    token, fetchImpl,
  ), 'appInfos');
  const infoDrafts = infos.filter(item => item.attributes?.state === DRAFT_STATE);
  const info = infoDrafts.length
    ? one(infoDrafts, 'editable app info')
    : one(infos.filter(item => item.attributes?.state === 'READY_FOR_SALE'), 'current app info');
  if (!infoDrafts.length && infos.length !== 1) {
    throw new Error('Multiple app info records make the primary localization ambiguous.');
  }
  const infoLocalizations = list(await getJson(
    `/v1/appInfos/${info.id}/appInfoLocalizations`
      + '?fields%5BappInfoLocalizations%5D=locale&limit=200',
    token, fetchImpl,
  ), 'appInfoLocalizations');
  one(infoLocalizations.filter(item => item.attributes?.locale === primaryLocale),
    `${primaryLocale} app info localization`);

  const versions = list(await getJson(
    `/v1/apps/${app.id}/appStoreVersions`
      + '?fields%5BappStoreVersions%5D=platform,versionString,appStoreState&limit=200',
    token, fetchImpl,
  ), 'appStoreVersions');
  const iosVersions = versions.filter(item => item.attributes?.platform === 'IOS');
  const target = iosVersions.filter(item => item.attributes?.versionString === marketingVersion);
  if (target.length > 1) {
    throw new Error(`Apple returned duplicate iOS ${marketingVersion} versions. No draft created.`);
  }
  if (target.length && target[0].attributes?.appStoreState !== DRAFT_STATE) {
    throw new Error(`iOS ${marketingVersion} already exists outside the editable draft state.`);
  }
  const targetVersion = target[0] ?? null;
  if (iosVersions.some(item => item.id !== targetVersion?.id
    && item.attributes?.appStoreState === DRAFT_STATE)) {
    throw new Error('Another editable iOS App Store version exists. No draft created.');
  }
  const versionLocalizations = targetVersion
    ? await localizations(targetVersion.id, token, fetchImpl) : [];
  const primaryMatches = versionLocalizations
    .filter(item => item.attributes?.locale === primaryLocale);
  if (primaryMatches.length > 1) {
    throw new Error(`Apple returned duplicate ${primaryLocale} iOS version localizations.`);
  }
  const fingerprint = createHash('sha256').update(JSON.stringify({
    appId: app.id, bundleId: BUNDLE_ID, primaryLocale, marketingVersion,
    infoId: info.id, infoState: info.attributes?.state,
    infoLocalizationIds: infoLocalizations.map(item => item.id).sort(),
    versions: versionInventory(versions),
    versionLocalizationIds: versionLocalizations.map(item => item.id).sort(),
  })).digest('hex');
  return {
    token, appId: app.id, bundleId: BUNDLE_ID, primaryLocale, marketingVersion,
    versionId: targetVersion?.id ?? null,
    versionState: targetVersion?.attributes?.appStoreState ?? null,
    primaryLocalizationId: primaryMatches[0]?.id ?? null,
    createVersion: !targetVersion,
    createPrimaryLocalization: !primaryMatches.length,
    fingerprint,
  };
}

async function postResource(path, type, body, token, fetchImpl) {
  if (path !== `/v1/${type}`
    || !['appStoreVersions', 'appStoreVersionLocalizations'].includes(type)) {
    throw new Error('Refusing an unexpected App Store Connect creation destination.');
  }
  const url = new URL(path, ORIGIN);
  let response;
  try {
    response = await fetchImpl(url, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      redirect: 'error',
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    throw new Error(`Apple did not confirm ${type} creation. Re-plan before retrying.`);
  }
  if (response.status !== 201) {
    throw new Error(`Apple rejected ${type} creation (HTTP ${response.status}). Re-plan before retrying.`);
  }
  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error(`Apple returned invalid JSON for ${type} creation. Re-plan before retrying.`);
  }
  if (result.data?.type !== type || !ID.test(result.data?.id)) {
    throw new Error(`Apple returned a different ${type} resource. Re-plan before retrying.`);
  }
  return result.data;
}

async function verifyVersion(versionId, marketingVersion, token, fetchImpl) {
  const response = await getJson(
    `/v1/appStoreVersions/${versionId}`
      + '?fields%5BappStoreVersions%5D=platform,versionString,appStoreState,releaseType',
    token, fetchImpl,
  );
  const version = response.data;
  if (version?.type !== 'appStoreVersions' || version.id !== versionId
    || version.attributes?.platform !== 'IOS'
    || version.attributes?.versionString !== marketingVersion
    || version.attributes?.appStoreState !== DRAFT_STATE) {
    throw new Error('Apple did not confirm the editable iOS draft. Inspect it before retrying.');
  }
  return version;
}

export async function prepareAppStoreDraft(credentials, marketingVersion, options = {}, fetchImpl = fetch) {
  const plan = await planAppStoreDraft(credentials, marketingVersion, fetchImpl);
  if (!options.apply) return { ...plan, applied: false, versionCreated: false, localizationCreated: false };
  if (!/^[a-f0-9]{64}$/.test(options.expectedPlanHash ?? '')
    || options.expectedPlanHash !== plan.fingerprint) {
    throw new Error('The live Apple draft inventory differs from the reviewed plan. No draft created.');
  }

  let versionId = plan.versionId;
  let versionCreated = false;
  let localizationCreated = false;
  if (plan.createVersion) {
    // Apple's create-version endpoint creates a PREPARE_FOR_SUBMISSION draft.
    // MANUAL is explicit; this workflow never calls review or release endpoints.
    const version = await postResource('/v1/appStoreVersions', 'appStoreVersions', {
      data: {
        type: 'appStoreVersions',
        attributes: { platform: 'IOS', versionString: marketingVersion, releaseType: 'MANUAL' },
        relationships: { app: { data: { type: 'apps', id: plan.appId } } },
      },
    }, plan.token, fetchImpl);
    versionId = version.id;
    versionCreated = true;
  }
  await verifyVersion(versionId, marketingVersion, plan.token, fetchImpl);

  // Apple may copy localizations from the preceding version. Create only the
  // primary locale when absent, leaving all existing locale text untouched.
  let locales = await localizations(versionId, plan.token, fetchImpl);
  let primary = locales.filter(item => item.attributes?.locale === plan.primaryLocale);
  if (primary.length > 1) {
    throw new Error('Apple returned duplicate primary iOS localizations. Inspect the draft.');
  }
  if (!primary.length) {
    const created = await postResource('/v1/appStoreVersionLocalizations',
      'appStoreVersionLocalizations', {
        data: {
          type: 'appStoreVersionLocalizations',
          attributes: { locale: plan.primaryLocale, supportUrl: SUPPORT_URL },
          relationships: { appStoreVersion: { data: { type: 'appStoreVersions', id: versionId } } },
        },
      }, plan.token, fetchImpl);
    if (created.attributes?.locale !== plan.primaryLocale) {
      throw new Error('Apple returned a different iOS localization. Inspect the draft.');
    }
    localizationCreated = true;
    locales = await localizations(versionId, plan.token, fetchImpl);
    primary = locales.filter(item => item.attributes?.locale === plan.primaryLocale);
    if (primary.length !== 1 || primary[0].id !== created.id
      || primary[0].attributes?.supportUrl !== SUPPORT_URL) {
      throw new Error('Apple did not confirm the primary iOS localization. Inspect the draft.');
    }
  }
  await verifyVersion(versionId, marketingVersion, plan.token, fetchImpl);
  return { ...plan, applied: true, versionId, primaryLocalizationId: primary[0].id,
    versionCreated, localizationCreated };
}

export function renderDraftSummary(result) {
  const action = result.applied
    ? (result.versionCreated ? 'created' : 'already existed')
    : (result.createVersion ? 'would create' : 'already exists');
  const localeAction = result.applied
    ? (result.localizationCreated ? 'created' : 'already existed')
    : (result.createPrimaryLocalization ? 'would create if Apple does not copy it' : 'already exists');
  return [
    '## HeyTim iOS App Store version draft', '',
    `Bundle ID: \`${result.bundleId}\`; version: \`${result.marketingVersion}\`; locale: \`${result.primaryLocale}\``,
    `Editable iOS draft: ${action}; primary version localization: ${localeAction}`,
    `Dry-run fingerprint: \`${result.fingerprint}\``, '',
    'This operation creates only an iOS PREPARE_FOR_SUBMISSION version and, if absent,'
      + ' its primary localization. It does not submit for review, upload a build,'
      + ' publish to the App Store, or change existing locale text.',
    'Run the separate listing metadata repair plan after the draft exists.', '',
  ].join('\n');
}

function parseArgs(argv) {
  const args = { apply: false };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--version' && !args.version) args.version = argv[++i];
    else if (argv[i] === '--expected-plan-hash' && !args.expectedPlanHash) {
      args.expectedPlanHash = argv[++i];
    } else if (argv[i] === '--apply' && !args.apply) args.apply = true;
    else throw new Error('Invalid App Store draft arguments.');
  }
  if (!VERSION.test(args.version ?? '') || (args.apply && !args.expectedPlanHash)
    || (!args.apply && args.expectedPlanHash)) {
    throw new Error('Use --version MAJOR.MINOR.PATCH; --apply also requires --expected-plan-hash.');
  }
  return args;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const result = await prepareAppStoreDraft({
    keyId: process.env.APP_STORE_CONNECT_KEY_ID,
    issuerId: process.env.APP_STORE_CONNECT_ISSUER_ID,
    privateKey: process.env.APP_STORE_CONNECT_PRIVATE_KEY,
  }, args.version, args);
  const summary = renderDraftSummary(result);
  if (process.env.GITHUB_STEP_SUMMARY) await appendFile(process.env.GITHUB_STEP_SUMMARY, summary);
  console.log(summary);
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  main().catch(error => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
