#!/usr/bin/env node

import { appendFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

import { getJson, makeAppStoreConnectToken } from './inspect-app-store-connect.mjs';

const BUNDLE_ID = 'ai.heytim.app';
const RESOURCE_ID = /^[A-Za-z0-9-]{1,128}$/;

function list(response, type) {
  if (!Array.isArray(response.data) || response.links?.next
    || response.data.some(item => item.type !== type || !RESOURCE_ID.test(item.id))) {
    throw new Error(`Apple returned an incomplete ${type} list for HeyTim.`);
  }
  return response.data;
}

function matchesPage(value, path) {
  if (typeof value !== 'string') return false;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname === 'heytim.ai'
      && url.pathname.replace(/\/$/, '') === path && !url.search && !url.hash;
  } catch {
    return false;
  }
}

function locale(value) {
  if (typeof value !== 'string' || !/^[a-z]{2,3}(?:-[A-Z0-9]{2,8})*$/.test(value)) {
    throw new Error('Apple returned an invalid HeyTim metadata locale.');
  }
  return value;
}

function state(value) {
  if (typeof value !== 'string' || !/^[A-Z_]{1,64}$/.test(value)) return 'UNKNOWN';
  return value;
}

export async function inspectAppStoreMetadata(credentials, fetchImpl = fetch) {
  const token = makeAppStoreConnectToken(credentials);
  const apps = list(await getJson(
    `/v1/apps?filter%5BbundleId%5D=${encodeURIComponent(BUNDLE_ID)}`
      + '&fields%5Bapps%5D=bundleId,primaryLocale&limit=2', token, fetchImpl,
  ), 'apps');
  if (apps.length !== 1 || apps[0].attributes?.bundleId !== BUNDLE_ID) {
    throw new Error(`The API key must resolve exactly one ${BUNDLE_ID} app.`);
  }
  const appId = apps[0].id;
  const primaryLocale = locale(apps[0].attributes?.primaryLocale);

  const infos = list(await getJson(
    `/v1/apps/${appId}/appInfos?fields%5BappInfos%5D=state&limit=200`,
    token, fetchImpl,
  ), 'appInfos');
  const appInfos = [];
  for (const info of infos) {
    const localizations = list(await getJson(
      `/v1/appInfos/${info.id}/appInfoLocalizations`
        + '?fields%5BappInfoLocalizations%5D=locale,name,privacyPolicyUrl,privacyChoicesUrl&limit=200',
      token, fetchImpl,
    ), 'appInfoLocalizations');
    appInfos.push({
      state: state(info.attributes?.state),
      localizations: localizations.map(item => ({
        locale: locale(item.attributes?.locale),
        heytimName: ['HeyTim', 'Hey Tim'].includes(item.attributes?.name),
        privacyPolicy: matchesPage(item.attributes?.privacyPolicyUrl, '/privacy'),
        privacyChoices: matchesPage(item.attributes?.privacyChoicesUrl, '/account-deletion'),
      })),
    });
  }

  const versions = list(await getJson(
    `/v1/apps/${appId}/appStoreVersions`
      + '?fields%5BappStoreVersions%5D=platform,versionString,appStoreState&limit=200',
    token, fetchImpl,
  ), 'appStoreVersions');
  const iosVersions = [];
  for (const version of versions.filter(item => item.attributes?.platform === 'IOS')) {
    const versionString = version.attributes?.versionString;
    if (typeof versionString !== 'string' || !/^\d+(?:\.\d+)*$/.test(versionString)) {
      throw new Error('Apple returned an invalid HeyTim iOS version.');
    }
    const localizations = list(await getJson(
      `/v1/appStoreVersions/${version.id}/appStoreVersionLocalizations`
        + '?fields%5BappStoreVersionLocalizations%5D=locale,supportUrl&limit=200',
      token, fetchImpl,
    ), 'appStoreVersionLocalizations');
    iosVersions.push({
      version: versionString,
      state: state(version.attributes?.appStoreState),
      localizations: localizations.map(item => ({
        locale: locale(item.attributes?.locale),
        support: matchesPage(item.attributes?.supportUrl, '/support'),
      })),
    });
  }
  return { bundleId: BUNDLE_ID, primaryLocale, appInfos, iosVersions };
}

export function renderMetadataSummary(inventory) {
  const lines = [
    '## HeyTim App Store listing metadata', '',
    `Bundle ID: \`${inventory.bundleId}\`; primary locale: \`${inventory.primaryLocale}\``,
    '',
    '| App info state | Locale | HeyTim name | Privacy policy URL | Account deletion URL |',
    '| --- | --- | --- | --- | --- |',
  ];
  for (const info of inventory.appInfos) {
    for (const item of info.localizations) {
      lines.push(`| ${info.state} | ${item.locale} | ${item.heytimName ? 'yes' : 'no'}`
        + ` | ${item.privacyPolicy ? 'yes' : 'no'} | ${item.privacyChoices ? 'yes' : 'no'} |`);
    }
  }
  if (inventory.appInfos.every(info => info.localizations.length === 0)) {
    lines.push('| No app info localization | — | no | no | no |');
  }
  lines.push('', '| iOS App Store version | State | Locale | Support URL |',
    '| --- | --- | --- | --- |');
  for (const version of inventory.iosVersions) {
    for (const item of version.localizations) {
      lines.push(`| ${version.version} | ${version.state} | ${item.locale}`
        + ` | ${item.support ? 'yes' : 'no'} |`);
    }
  }
  if (inventory.iosVersions.every(version => version.localizations.length === 0)) {
    lines.push('| No iOS App Store version localization | — | — | no |');
  }
  lines.push('', 'A no means the live Apple value is absent or differs from the HeyTim page.'
    + ' This read-only check does not change the listing or establish support email delivery.', '');
  return lines.join('\n');
}

async function main() {
  const inventory = await inspectAppStoreMetadata({
    keyId: process.env.APP_STORE_CONNECT_KEY_ID,
    issuerId: process.env.APP_STORE_CONNECT_ISSUER_ID,
    privateKey: process.env.APP_STORE_CONNECT_PRIVATE_KEY,
  });
  if (!process.env.GITHUB_STEP_SUMMARY) {
    throw new Error('GITHUB_STEP_SUMMARY is missing from the protected production environment.');
  }
  await appendFile(process.env.GITHUB_STEP_SUMMARY, renderMetadataSummary(inventory));
  const primaryInfoReady = inventory.appInfos.some(info => info.localizations.some(item =>
    item.locale === inventory.primaryLocale && item.heytimName && item.privacyPolicy));
  const privacyChoicesLinked = inventory.appInfos.some(info => info.localizations.some(item =>
    item.locale === inventory.primaryLocale && item.privacyChoices));
  const iosSupportReady = inventory.iosVersions.some(version => version.localizations.some(item =>
    item.locale === inventory.primaryLocale && item.support));
  console.log(`HeyTim listing: primary-locale name/privacy ${primaryInfoReady ? 'match' : 'need review'};`
    + ` optional privacy choices URL ${privacyChoicesLinked ? 'matches' : 'not linked'};`
    + ` iOS support URL ${iosSupportReady ? 'matches' : 'needs review'}.`);
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  main().catch(() => {
    console.error('HeyTim App Store metadata inventory failed without exposing its API response.');
    process.exitCode = 1;
  });
}
