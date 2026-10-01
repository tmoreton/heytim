#!/usr/bin/env node

import { appendFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

import { getJson, makeAppStoreConnectToken } from './inspect-app-store-connect.mjs';

const BUNDLE_ID = 'ai.heytim.app';
const RESOURCE_ID = /^[A-Za-z0-9-]{1,128}$/;
const LEGACY_BRAND = /froggy\s*bot|frog\s*bot/i;

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

function presentListingText(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function brandFree(value) {
  return presentListingText(value) && !LEGACY_BRAND.test(value);
}

async function screenshotInventory(localizationId, token, fetchImpl) {
  const sets = list(await getJson(
    `/v1/appStoreVersionLocalizations/${localizationId}/appScreenshotSets`
      + '?fields%5BappScreenshotSets%5D=screenshotDisplayType&limit=200',
    token, fetchImpl,
  ), 'appScreenshotSets');
  let total = 0;
  let ready = 0;
  for (const set of sets) {
    const displayType = set.attributes?.screenshotDisplayType;
    if (typeof displayType !== 'string' || !/^APP_[A-Z0-9_]{1,64}$/.test(displayType)) {
      throw new Error('Apple returned an invalid HeyTim screenshot display type.');
    }
    const screenshots = list(await getJson(
      `/v1/appScreenshotSets/${set.id}/appScreenshots`
        + '?fields%5BappScreenshots%5D=assetDeliveryState&limit=200',
      token, fetchImpl,
    ), 'appScreenshots');
    total += screenshots.length;
    ready += screenshots.filter(item => item.attributes?.assetDeliveryState?.state === 'COMPLETE').length;
  }
  return { sets: sets.length, total, ready };
}

async function reviewInventory(reviewDetailId, token, fetchImpl) {
  if (reviewDetailId == null) return { detailPresent: false, notesPresent: false };
  if (!RESOURCE_ID.test(reviewDetailId)) {
    throw new Error('Apple returned an invalid HeyTim App Review detail ID.');
  }
  const response = await getJson(
    `/v1/appStoreReviewDetails/${reviewDetailId}`
      + '?fields%5BappStoreReviewDetails%5D=notes',
    token, fetchImpl,
  );
  if (response.data?.type !== 'appStoreReviewDetails' || response.data.id !== reviewDetailId) {
    throw new Error('Apple returned an unexpected HeyTim App Review detail.');
  }
  return {
    detailPresent: true,
    notesPresent: presentListingText(response.data.attributes?.notes),
  };
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
        + '?fields%5BappInfoLocalizations%5D=locale,name,subtitle,privacyPolicyUrl,privacyChoicesUrl&limit=200',
      token, fetchImpl,
    ), 'appInfoLocalizations');
    appInfos.push({
      state: state(info.attributes?.state),
      localizations: localizations.map(item => ({
        locale: locale(item.attributes?.locale),
        heytimName: ['HeyTim', 'Hey Tim'].includes(item.attributes?.name),
        subtitlePresent: presentListingText(item.attributes?.subtitle),
        subtitleBrandFree: brandFree(item.attributes?.subtitle),
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
        + '?fields%5BappStoreVersionLocalizations%5D=locale,description,supportUrl&limit=200',
      token, fetchImpl,
    ), 'appStoreVersionLocalizations');
    const reviewLink = await getJson(
      `/v1/appStoreVersions/${version.id}/relationships/appStoreReviewDetail`,
      token, fetchImpl,
    );
    const reviewDetail = reviewLink?.data;
    if (reviewLink == null || !Object.hasOwn(reviewLink, 'data')
      || (reviewDetail != null && (reviewDetail.type !== 'appStoreReviewDetails'
        || !RESOURCE_ID.test(reviewDetail.id)))) {
      throw new Error('Apple returned an unexpected HeyTim App Review relationship.');
    }
    const review = await reviewInventory(reviewDetail?.id, token, fetchImpl);
    const inspectedLocalizations = [];
    for (const item of localizations) {
      inspectedLocalizations.push({
        locale: locale(item.attributes?.locale),
        descriptionPresent: presentListingText(item.attributes?.description),
        descriptionBrandFree: brandFree(item.attributes?.description),
        support: matchesPage(item.attributes?.supportUrl, '/support'),
        screenshots: await screenshotInventory(item.id, token, fetchImpl),
      });
    }
    iosVersions.push({
      version: versionString,
      state: state(version.attributes?.appStoreState),
      review,
      localizations: inspectedLocalizations,
    });
  }
  return { bundleId: BUNDLE_ID, primaryLocale, appInfos, iosVersions };
}

export function renderMetadataSummary(inventory) {
  const lines = [
    '## HeyTim App Store listing metadata', '',
    `Bundle ID: \`${inventory.bundleId}\`; primary locale: \`${inventory.primaryLocale}\``,
    '',
    '| App info state | Locale | HeyTim name | Subtitle present | No legacy brand in subtitle | Privacy policy URL | Account deletion URL |',
    '| --- | --- | --- | --- | --- | --- | --- |',
  ];
  for (const info of inventory.appInfos) {
    for (const item of info.localizations) {
      lines.push(`| ${info.state} | ${item.locale} | ${item.heytimName ? 'yes' : 'no'}`
        + ` | ${item.subtitlePresent ? 'yes' : 'no'} | ${item.subtitleBrandFree ? 'yes' : 'no'}`
        + ` | ${item.privacyPolicy ? 'yes' : 'no'} | ${item.privacyChoices ? 'yes' : 'no'} |`);
    }
  }
  if (inventory.appInfos.every(info => info.localizations.length === 0)) {
    lines.push('| No app info localization | — | no | no | no | no | no |');
  }
  lines.push('', '| iOS App Store version | State | Locale | Description present | No legacy brand in description | Support URL | Ready screenshots | App Review detail | Review notes |',
    '| --- | --- | --- | --- | --- | --- | --- | --- | --- |');
  for (const version of inventory.iosVersions) {
    for (const item of version.localizations) {
      lines.push(`| ${version.version} | ${version.state} | ${item.locale}`
        + ` | ${item.descriptionPresent ? 'yes' : 'no'}`
        + ` | ${item.descriptionBrandFree ? 'yes' : 'no'}`
        + ` | ${item.support ? 'yes' : 'no'}`
        + ` | ${item.screenshots.ready}/${item.screenshots.total} in ${item.screenshots.sets} set(s)`
        + ` | ${version.review.detailPresent ? 'yes' : 'no'}`
        + ` | ${version.review.notesPresent ? 'yes' : 'no'} |`);
    }
  }
  if (inventory.iosVersions.every(version => version.localizations.length === 0)) {
    lines.push('| No iOS App Store version localization | — | — | no | no | no | 0/0 | no | no |');
  }
  lines.push('', 'A no means the live Apple value is absent or differs from the HeyTim page.'
    + ' Ready screenshots have completed Apple processing. Review notes are reported by presence only.'
    + ' This read-only check does not change the listing, prove that required screenshot sizes are met,'
    + ' or establish support email delivery.', '');
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
