#!/usr/bin/env node

import { createHash } from 'node:crypto';
import { appendFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

import { getJson, makeAppStoreConnectToken } from './inspect-app-store-connect.mjs';

const API_ORIGIN = 'https://api.appstoreconnect.apple.com';
const BUNDLE_ID = 'ai.heytim.app';
const ID = /^[A-Za-z0-9-]{1,128}$/;
const VERSION = /^\d+\.\d+\.\d+$/;
const LOCALE = /^[a-z]{2,3}(?:-[A-Z0-9]{2,8})*$/;
const EDITABLE_VERSION_STATE = 'PREPARE_FOR_SUBMISSION';
const TARGET = Object.freeze({
  name: 'HeyTim',
  privacyPolicyUrl: 'https://heytim.ai/privacy/',
  supportUrl: 'https://heytim.ai/support/',
});

function completeList(response, type) {
  if (!Array.isArray(response.data) || response.links?.next
    || response.data.some(item => item?.type !== type || !ID.test(item.id))) {
    throw new Error(`Apple returned an incomplete or invalid ${type} list for HeyTim.`);
  }
  return response.data;
}

function exactlyOne(items, label) {
  if (items.length !== 1) {
    throw new Error(`Expected exactly one ${label}; found ${items.length}. No metadata changed.`);
  }
  return items[0];
}

function optionalText(value, label) {
  if (value == null) return null;
  if (typeof value !== 'string' || value.length > 2048) {
    throw new Error(`Apple returned invalid ${label} for HeyTim.`);
  }
  return value;
}

function primaryLocalization(items, primaryLocale, label) {
  return exactlyOne(items.filter(item => item.attributes?.locale === primaryLocale),
    `${primaryLocale} ${label}`);
}

export async function prepareMetadataRepair(credentials, marketingVersion, fetchImpl = fetch) {
  if (!VERSION.test(marketingVersion)) {
    throw new Error('The target iOS App Store version must be MAJOR.MINOR.PATCH.');
  }
  const token = makeAppStoreConnectToken(credentials);
  const apps = completeList(await getJson(
    `/v1/apps?filter%5BbundleId%5D=${encodeURIComponent(BUNDLE_ID)}`
      + '&fields%5Bapps%5D=bundleId,primaryLocale&limit=2', token, fetchImpl,
  ), 'apps');
  const app = exactlyOne(apps, `${BUNDLE_ID} app`);
  if (app.attributes?.bundleId !== BUNDLE_ID) {
    throw new Error(`The API key did not resolve ${BUNDLE_ID}. No metadata changed.`);
  }
  const primaryLocale = app.attributes?.primaryLocale;
  if (typeof primaryLocale !== 'string' || !LOCALE.test(primaryLocale)) {
    throw new Error('Apple returned an invalid HeyTim primary locale.');
  }

  const infos = completeList(await getJson(
    `/v1/apps/${app.id}/appInfos?fields%5BappInfos%5D=state&limit=200`,
    token, fetchImpl,
  ), 'appInfos');
  const versions = completeList(await getJson(
    `/v1/apps/${app.id}/appStoreVersions`
      + '?fields%5BappStoreVersions%5D=platform,versionString,appStoreState&limit=200',
    token, fetchImpl,
  ), 'appStoreVersions');
  const version = exactlyOne(versions.filter(item => item.attributes?.platform === 'IOS'
    && item.attributes?.versionString === marketingVersion
    && item.attributes?.appStoreState === EDITABLE_VERSION_STATE),
  `editable iOS ${marketingVersion} App Store version`);

  // Apple can retain the current app info as READY_FOR_SALE while an iOS draft exists.
  const drafts = infos.filter(item => item.attributes?.state === EDITABLE_VERSION_STATE);
  const info = drafts.length
    ? exactlyOne(drafts, 'editable app info')
    : exactlyOne(infos.filter(item => item.attributes?.state === 'READY_FOR_SALE'),
      'current app info');
  if (!drafts.length && infos.length !== 1) {
    throw new Error('Multiple app info records make the current localization ambiguous. No metadata changed.');
  }

  const infoLocalizations = completeList(await getJson(
    `/v1/appInfos/${info.id}/appInfoLocalizations`
      + '?fields%5BappInfoLocalizations%5D=locale,name,privacyPolicyUrl&limit=200',
    token, fetchImpl,
  ), 'appInfoLocalizations');
  const infoLocalization = primaryLocalization(infoLocalizations, primaryLocale,
    'app info localization');
  const versionLocalizations = completeList(await getJson(
    `/v1/appStoreVersions/${version.id}/appStoreVersionLocalizations`
      + '?fields%5BappStoreVersionLocalizations%5D=locale,supportUrl&limit=200',
    token, fetchImpl,
  ), 'appStoreVersionLocalizations');
  const versionLocalization = primaryLocalization(versionLocalizations, primaryLocale,
    'iOS version localization');

  const current = {
    name: optionalText(infoLocalization.attributes?.name, 'app name'),
    privacyPolicyUrl: optionalText(infoLocalization.attributes?.privacyPolicyUrl, 'privacy URL'),
    supportUrl: optionalText(versionLocalization.attributes?.supportUrl, 'support URL'),
  };
  const changes = {
    appInfo: Object.fromEntries(['name', 'privacyPolicyUrl']
      .filter(key => current[key] !== TARGET[key]).map(key => [key, TARGET[key]])),
    iosVersion: current.supportUrl === TARGET.supportUrl ? {} : { supportUrl: TARGET.supportUrl },
  };
  const fingerprint = createHash('sha256').update(JSON.stringify({
    bundleId: BUNDLE_ID, appId: app.id, primaryLocale,
    infoId: info.id, infoState: info.attributes.state, infoLocalizationId: infoLocalization.id,
    versionId: version.id, versionState: version.attributes.appStoreState,
    marketingVersion, versionLocalizationId: versionLocalization.id, current, target: TARGET,
  })).digest('hex');

  return {
    token, bundleId: BUNDLE_ID, primaryLocale, marketingVersion,
    appInfoState: info.attributes.state, versionState: version.attributes.appStoreState,
    fingerprint, changes,
    appInfoLocalizationId: infoLocalization.id,
    versionLocalizationId: versionLocalization.id,
  };
}

async function patchLocalization(path, type, id, attributes, token, fetchImpl) {
  const url = new URL(path, API_ORIGIN);
  if (url.origin !== API_ORIGIN || url.pathname !== `/v1/${type}/${id}`) {
    throw new Error('Refusing an unexpected App Store Connect update destination.');
  }
  let response;
  try {
    response = await fetchImpl(url, {
      method: 'PATCH',
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ data: { type, id, attributes } }),
      redirect: 'error',
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    throw new Error(`Apple did not accept the ${type} update.`);
  }
  if (!response.ok) {
    throw new Error(`Apple rejected the ${type} update (HTTP ${response.status}).`);
  }
  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error(`Apple returned invalid JSON for the ${type} update.`);
  }
  if (result.data?.type !== type || result.data?.id !== id) {
    throw new Error(`Apple returned a different ${type} resource after update.`);
  }
}

async function verifyLocalization(type, id, primaryLocale, expected, token, fetchImpl) {
  const fields = ['locale', ...Object.keys(expected)].join(',');
  const response = await getJson(`/v1/${type}/${id}?fields%5B${type}%5D=${fields}`,
    token, fetchImpl);
  if (response.data?.type !== type || response.data?.id !== id
    || response.data?.attributes?.locale !== primaryLocale
    || Object.entries(expected).some(([key, value]) => response.data.attributes[key] !== value)) {
    throw new Error(`Apple did not confirm the ${type} update. Inspect the listing before retrying.`);
  }
}

export async function repairMetadata(credentials, marketingVersion, options = {}, fetchImpl = fetch) {
  const plan = await prepareMetadataRepair(credentials, marketingVersion, fetchImpl);
  if (!options.apply) return { ...plan, applied: false };
  if (!/^[a-f0-9]{64}$/.test(options.expectedPlanHash ?? '')
    || options.expectedPlanHash !== plan.fingerprint) {
    throw new Error('The live metadata differs from the reviewed dry run. No metadata changed.');
  }
  if (Object.keys(plan.changes.appInfo).length) {
    await patchLocalization(`/v1/appInfoLocalizations/${plan.appInfoLocalizationId}`,
      'appInfoLocalizations', plan.appInfoLocalizationId, plan.changes.appInfo,
      plan.token, fetchImpl);
    await verifyLocalization('appInfoLocalizations', plan.appInfoLocalizationId,
      plan.primaryLocale, plan.changes.appInfo, plan.token, fetchImpl);
  }
  if (Object.keys(plan.changes.iosVersion).length) {
    await patchLocalization(`/v1/appStoreVersionLocalizations/${plan.versionLocalizationId}`,
      'appStoreVersionLocalizations', plan.versionLocalizationId, plan.changes.iosVersion,
      plan.token, fetchImpl);
    await verifyLocalization('appStoreVersionLocalizations', plan.versionLocalizationId,
      plan.primaryLocale, plan.changes.iosVersion, plan.token, fetchImpl);
  }
  return { ...plan, applied: true };
}

export function renderRepairSummary(plan) {
  const fields = [
    ...Object.keys(plan.changes.appInfo),
    ...Object.keys(plan.changes.iosVersion),
  ];
  return [
    '## HeyTim App Store listing repair', '',
    `Bundle ID: \`${plan.bundleId}\`; primary locale: \`${plan.primaryLocale}\`;`
      + ` iOS draft: \`${plan.marketingVersion}\``,
    `App info state: \`${plan.appInfoState}\`; iOS version state: \`${plan.versionState}\``,
    `Fields ${plan.applied ? 'updated' : 'proposed'}: ${fields.length ? fields.join(', ') : 'none'}`,
    `Dry-run fingerprint: \`${plan.fingerprint}\``,
    '',
    'Only the primary-locale app name, privacy policy URL, and iOS support URL are in scope.'
      + ' Existing subtitle, descriptions, other locales, and privacy choices URL are untouched.',
    '',
  ].join('\n');
}

function parseArgs(argv) {
  const args = { apply: false };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--version' && !args.version) args.version = argv[++i];
    else if (argv[i] === '--expected-plan-hash' && !args.expectedPlanHash) {
      args.expectedPlanHash = argv[++i];
    } else if (argv[i] === '--apply' && !args.apply) args.apply = true;
    else throw new Error('Invalid App Store metadata repair arguments.');
  }
  if (!VERSION.test(args.version ?? '') || (args.apply && !args.expectedPlanHash)
    || (!args.apply && args.expectedPlanHash)) {
    throw new Error('Use --version MAJOR.MINOR.PATCH; --apply also requires --expected-plan-hash.');
  }
  return args;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const plan = await repairMetadata({
    keyId: process.env.APP_STORE_CONNECT_KEY_ID,
    issuerId: process.env.APP_STORE_CONNECT_ISSUER_ID,
    privateKey: process.env.APP_STORE_CONNECT_PRIVATE_KEY,
  }, args.version, args);
  const summary = renderRepairSummary(plan);
  if (process.env.GITHUB_STEP_SUMMARY) await appendFile(process.env.GITHUB_STEP_SUMMARY, summary);
  console.log(summary);
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  main().catch(error => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
