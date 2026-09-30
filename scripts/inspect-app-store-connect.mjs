#!/usr/bin/env node

import { createPrivateKey, createSign } from 'node:crypto';
import { appendFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const API_ORIGIN = 'https://api.appstoreconnect.apple.com';
const BUNDLE_ID = 'ai.heytim.app';

class InventoryError extends Error {}

function required(value, name) {
  if (typeof value !== 'string' || !value.trim()) {
    throw new InventoryError(`${name} is missing from the protected production environment.`);
  }
  return value.trim();
}

export function makeAppStoreConnectToken({ keyId, issuerId, privateKey }, now = Date.now()) {
  const kid = required(keyId, 'APP_STORE_CONNECT_KEY_ID');
  const iss = required(issuerId, 'APP_STORE_CONNECT_ISSUER_ID');
  const pem = required(privateKey, 'APP_STORE_CONNECT_PRIVATE_KEY');
  if (!/^[A-Za-z0-9]+$/.test(kid) || !/^[0-9a-fA-F-]{36}$/.test(iss)) {
    throw new InventoryError('The protected App Store Connect key identifiers are invalid.');
  }

  let signingKey;
  try {
    signingKey = createPrivateKey(pem);
  } catch {
    throw new InventoryError('The protected App Store Connect private key is invalid.');
  }
  if (signingKey.asymmetricKeyType !== 'ec'
    || signingKey.asymmetricKeyDetails?.namedCurve !== 'prime256v1') {
    throw new InventoryError('The protected App Store Connect private key is not ES256.');
  }

  const encode = object => Buffer.from(JSON.stringify(object)).toString('base64url');
  const iat = Math.floor(now / 1000);
  const unsigned = `${encode({ alg: 'ES256', kid, typ: 'JWT' })}.${encode({
    iss, iat, exp: iat + 300, aud: 'appstoreconnect-v1',
  })}`;
  const signer = createSign('SHA256');
  signer.update(unsigned);
  signer.end();
  const signature = signer.sign({ key: signingKey, dsaEncoding: 'ieee-p1363' });
  return `${unsigned}.${signature.toString('base64url')}`;
}

export async function getJson(path, token, fetchImpl) {
  const url = new URL(path, API_ORIGIN);
  if (url.origin !== API_ORIGIN || !url.pathname.startsWith('/v1/')) {
    throw new InventoryError('The inventory requested an unexpected API destination.');
  }
  let response;
  try {
    response = await fetchImpl(url, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
      redirect: 'error',
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    throw new InventoryError(`Apple did not return ${url.pathname}.`);
  }
  if (!response.ok) {
    throw new InventoryError(`Apple rejected ${url.pathname} (HTTP ${response.status}).`);
  }
  try {
    return await response.json();
  } catch {
    throw new InventoryError(`Apple returned invalid JSON for ${url.pathname}.`);
  }
}

function safeField(value, label, pattern) {
  if (typeof value !== 'string' || !pattern.test(value)) {
    throw new InventoryError(`Apple returned an invalid ${label} for HeyTim.`);
  }
  return value;
}

export async function inspectAppStoreConnect(credentials, fetchImpl = fetch) {
  const token = makeAppStoreConnectToken(credentials);
  let expectedTesterEmail;
  let identitySource;
  if (credentials.expectedTesterEmail?.trim()) {
    expectedTesterEmail = credentials.expectedTesterEmail.trim().toLowerCase();
    identitySource = 'Expected owner';
  } else {
    const users = await getJson(
      '/v1/users?filter%5Broles%5D=ACCOUNT_HOLDER&fields%5Busers%5D=username,roles&limit=2',
      token,
      fetchImpl,
    );
    if (!Array.isArray(users.data) || users.data.length !== 1
      || users.data[0]?.type !== 'users'
      || !users.data[0]?.attributes?.roles?.includes('ACCOUNT_HOLDER')) {
      throw new InventoryError('Apple must identify exactly one Account Holder for private membership inspection.');
    }
    expectedTesterEmail = users.data[0].attributes.username?.trim().toLowerCase();
    identitySource = 'Apple Account Holder';
  }
  if (typeof expectedTesterEmail !== 'string' || expectedTesterEmail.length > 320
    || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(expectedTesterEmail)) {
    throw new InventoryError('The private internal tester identity is invalid.');
  }
  const apps = await getJson(
    `/v1/apps?filter%5BbundleId%5D=${encodeURIComponent(BUNDLE_ID)}`
      + '&fields%5Bapps%5D=bundleId&limit=2',
    token,
    fetchImpl,
  );
  if (!Array.isArray(apps.data) || apps.data.length !== 1
    || apps.data[0]?.type !== 'apps'
    || apps.data[0]?.attributes?.bundleId !== BUNDLE_ID) {
    throw new InventoryError(`The API key must resolve exactly one ${BUNDLE_ID} app.`);
  }
  const appId = safeField(apps.data[0].id, 'app ID', /^[A-Za-z0-9-]{1,128}$/);

  const builds = await getJson(
    `/v1/builds?filter%5Bapp%5D=${encodeURIComponent(appId)}`
      + '&filter%5BpreReleaseVersion.platform%5D=IOS'
      + '&include=preReleaseVersion'
      + '&fields%5Bbuilds%5D=version,uploadedDate,processingState,buildAudienceType,preReleaseVersion'
      + '&fields%5BpreReleaseVersions%5D=version,platform'
      + '&sort=-uploadedDate&limit=10',
    token,
    fetchImpl,
  );
  if (!Array.isArray(builds.data) || !Array.isArray(builds.included ?? [])) {
    throw new InventoryError('Apple returned an invalid HeyTim build list.');
  }
  const prereleases = new Map((builds.included ?? [])
    .filter(item => item.type === 'preReleaseVersions')
    .map(item => [item.id, item.attributes]));
  const recentBuilds = builds.data.map(build => {
    if (build.type !== 'builds') {
      throw new InventoryError('Apple returned an unexpected build resource.');
    }
    const prereleaseId = build.relationships?.preReleaseVersion?.data?.id;
    const prerelease = prereleases.get(prereleaseId);
    if (prerelease && prerelease.platform !== 'IOS') {
      throw new InventoryError('Apple returned a non-iOS prerelease version for an iOS build.');
    }
    const uploaded = build.attributes?.uploadedDate
      ? new Date(build.attributes.uploadedDate) : null;
    return {
      marketingVersion: prerelease
        ? safeField(prerelease.version, 'marketing version', /^[0-9]+(?:\.[0-9]+)*$/)
        : 'UNKNOWN',
      buildNumber: safeField(build.attributes?.version, 'build number', /^[A-Za-z0-9._-]{1,64}$/),
      processingState: safeField(build.attributes?.processingState, 'processing state', /^[A-Z_]{1,32}$/),
      audience: build.attributes?.buildAudienceType
        ? safeField(build.attributes.buildAudienceType, 'build audience', /^[A-Z_]{1,32}$/)
        : 'UNKNOWN',
      uploadedUtc: uploaded && Number.isFinite(uploaded.getTime())
        ? uploaded.toISOString() : 'UNKNOWN',
    };
  }).slice(0, 5);

  let next = `/v1/apps/${appId}/betaGroups`
    + '?fields%5BbetaGroups%5D=isInternalGroup,hasAccessToAllBuilds&limit=200';
  let internalGroupCount = 0;
  let allBuildsInternalGroupCount = 0;
  let ownerInInternalGroup = false;
  let ownerInAllBuildsInternalGroup = false;
  let ownerAcceptedOrInstalled = false;
  for (let page = 0; next && page < 20; page += 1) {
    const groups = await getJson(next, token, fetchImpl);
    if (!Array.isArray(groups.data)) {
      throw new InventoryError('Apple returned an invalid HeyTim beta group list.');
    }
    for (const group of groups.data) {
      if (group.type !== 'betaGroups') {
        throw new InventoryError('Apple returned an unexpected beta group resource.');
      }
      if (group.attributes?.isInternalGroup === true) {
        internalGroupCount += 1;
        if (group.attributes.hasAccessToAllBuilds === true) {
          allBuildsInternalGroupCount += 1;
        }
        const groupId = safeField(group.id, 'internal group ID', /^[A-Za-z0-9-]{1,128}$/);
        let testersNext = `/v1/betaGroups/${groupId}/betaTesters`
          + '?fields%5BbetaTesters%5D=email,state&limit=200';
        for (let testerPage = 0; testersNext && testerPage < 20; testerPage += 1) {
          const testers = await getJson(testersNext, token, fetchImpl);
          if (!Array.isArray(testers.data)) {
            throw new InventoryError('Apple returned an invalid internal tester list.');
          }
          for (const tester of testers.data) {
            if (tester.type !== 'betaTesters') {
              throw new InventoryError('Apple returned an unexpected internal tester resource.');
            }
            const email = tester.attributes?.email;
            const state = tester.attributes?.state;
            if (typeof email === 'string' && email.trim().toLowerCase() === expectedTesterEmail
              && ['INVITED', 'ACCEPTED', 'INSTALLED'].includes(state)) {
              ownerInInternalGroup = true;
              ownerInAllBuildsInternalGroup ||= group.attributes.hasAccessToAllBuilds === true;
              ownerAcceptedOrInstalled ||= ['ACCEPTED', 'INSTALLED'].includes(state);
            }
          }
          const testerLink = testers.links?.next;
          if (testerLink) {
            const nextUrl = new URL(testerLink, API_ORIGIN);
            if (nextUrl.origin !== API_ORIGIN
              || nextUrl.pathname !== `/v1/betaGroups/${groupId}/betaTesters`) {
              throw new InventoryError('Apple returned an unexpected internal tester page.');
            }
            testersNext = `${nextUrl.pathname}${nextUrl.search}`;
          } else {
            testersNext = null;
          }
        }
        if (testersNext) {
          throw new InventoryError('Apple returned too many internal tester pages to verify safely.');
        }
      }
    }
    const nextLink = groups.links?.next;
    if (nextLink) {
      const nextUrl = new URL(nextLink, API_ORIGIN);
      if (nextUrl.origin !== API_ORIGIN
        || nextUrl.pathname !== `/v1/apps/${appId}/betaGroups`) {
        throw new InventoryError('Apple returned an unexpected beta group page.');
      }
      next = `${nextUrl.pathname}${nextUrl.search}`;
    } else {
      next = null;
    }
  }
  if (next) {
    throw new InventoryError('Apple returned too many beta group pages to verify safely.');
  }

  return {
    bundleId: BUNDLE_ID, identitySource, recentBuilds, internalGroupCount, allBuildsInternalGroupCount,
    ownerInInternalGroup, ownerInAllBuildsInternalGroup, ownerAcceptedOrInstalled,
  };
}

export function renderSummary(inventory) {
  const lines = [
    '## HeyTim App Store Connect inventory',
    '',
    `Bundle ID: \`${inventory.bundleId}\``,
    `Internal tester group available: **${inventory.internalGroupCount > 0 ? 'yes' : 'no'}**`,
    `Internal group with access to all builds: **${inventory.allBuildsInternalGroupCount > 0 ? 'yes' : 'no'}**`,
    `${inventory.identitySource ?? 'Expected owner'} in an internal group: **${inventory.ownerInInternalGroup ? 'yes' : 'no'}**`,
    `${inventory.identitySource ?? 'Expected owner'} in an all-builds internal group: **${inventory.ownerInAllBuildsInternalGroup ? 'yes' : 'no'}**`,
    `${inventory.identitySource ?? 'Expected owner'} accepted or installed: **${inventory.ownerAcceptedOrInstalled ? 'yes' : 'no'}**`,
    '',
    '| iOS version | Build | Processing | Audience | Uploaded (UTC) |',
    '| --- | --- | --- | --- | --- |',
  ];
  for (const build of inventory.recentBuilds) {
    lines.push(`| ${build.marketingVersion} | ${build.buildNumber} | ${build.processingState}`
      + ` | ${build.audience} | ${build.uploadedUtc} |`);
  }
  if (inventory.recentBuilds.length === 0) {
    lines.push('| No iOS builds | — | — | — | — |');
  }
  lines.push('', 'This read-only inventory does not upload a build or prove physical-device delivery.', '');
  return lines.join('\n');
}

export function assertInternalOwnerReady(inventory) {
  if (!inventory.ownerInAllBuildsInternalGroup || !inventory.ownerAcceptedOrInstalled) {
    throw new InventoryError('The expected owner is not accepted in an internal tester group with access to all builds.');
  }
}

async function main() {
  if (process.argv.length > 3
    || (process.argv.length === 3 && process.argv[2] !== '--require-owner-ready')) {
    throw new InventoryError('The inventory accepts only --require-owner-ready.');
  }
  const inventory = await inspectAppStoreConnect({
    keyId: process.env.APP_STORE_CONNECT_KEY_ID,
    issuerId: process.env.APP_STORE_CONNECT_ISSUER_ID,
    privateKey: process.env.APP_STORE_CONNECT_PRIVATE_KEY,
    expectedTesterEmail: process.env.APP_STORE_CONNECT_EXPECTED_INTERNAL_TESTER_EMAIL,
  });
  const summaryPath = required(process.env.GITHUB_STEP_SUMMARY, 'GITHUB_STEP_SUMMARY');
  await appendFile(summaryPath, renderSummary(inventory));
  if (process.argv[2] === '--require-owner-ready') {
    assertInternalOwnerReady(inventory);
  }
  console.log(`HeyTim iOS inventory: ${inventory.recentBuilds.length} recent build(s);`
    + ` ${inventory.identitySource} in all-builds internal group: ${inventory.ownerInAllBuildsInternalGroup ? 'yes' : 'no'};`
    + ` accepted or installed: ${inventory.ownerAcceptedOrInstalled ? 'yes' : 'no'}.`);
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  main().catch(error => {
    console.error(error instanceof InventoryError
      ? error.message
      : 'HeyTim App Store Connect inventory failed without exposing its API response.');
    process.exitCode = 1;
  });
}
