#!/usr/bin/env node

// One-off cleanup for the bot left by production workflow run 36767466962.
// Remove this script and its workflow call after the guarded deletion succeeds.
const expected = Object.freeze({
  apiUrl: 'https://srrkqsqrqd.execute-api.us-east-1.amazonaws.com',
  issuer: 'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_biJejrNQF',
  userId: '74b83418-6051-70c9-07f9-35a32cf51812',
  botId: 'ff0e248b-650f-4654-9572-afc76c91c046',
  turnId: '5217364f-f690-4d54-8494-137d29a43a83',
  name: 'Approval Check 20260930195740',
  tagline: 'Temporary approval workflow verification bot.',
  createdAt: '2026-09-30T19:58:26.003+00:00',
});

const fail = (message) => { throw new Error(message); };
const apiUrl = process.env.HEYTIM_API_URL;
const idToken = process.env.HEYTIM_ID_TOKEN;
if (apiUrl !== expected.apiUrl || !idToken) {
  fail('The exact destination API URL and an ID token are required for orphan cleanup.');
}

let claims;
try {
  claims = JSON.parse(Buffer.from(idToken.split('.')[1], 'base64url').toString('utf8'));
} catch {
  fail('The release-test ID token could not be inspected.');
}
if (claims.iss !== expected.issuer || claims.sub !== expected.userId || claims.token_use !== 'id') {
  fail('The ID token does not belong to the exact destination release-test account.');
}

const request = async (method, path) => {
  const response = await fetch(`${apiUrl}${path}`, {
    method,
    headers: { authorization: `Bearer ${idToken}` },
    signal: AbortSignal.timeout(25_000),
  });
  if (!response.ok) fail(`${method} ${path} failed with HTTP ${response.status}.`);
  return response.json();
};

const bootstrap = await request('GET', '/bootstrap');
if (!Array.isArray(bootstrap.bots)) fail('The release-test bot list is unavailable.');
const bot = bootstrap.bots.find((item) => item.id === expected.botId);
if (!bot) {
  console.log('The exact orphan release-test bot is already absent.');
  process.exit(0);
}
if (bot.name !== expected.name || bot.tagline !== expected.tagline
    || bot.createdAt !== expected.createdAt || bot.systemRole ||
    !Array.isArray(bot.toolIds) || bot.toolIds.length !== 1 || bot.toolIds[0] !== 'browser') {
  fail('The matching bot ID does not have the exact synthetic test identity.');
}

const path = `/bots/${expected.botId}`;
const { messages } = await request('GET', `${path}/messages`);
if (!Array.isArray(messages)) fail('The synthetic bot turn list is unavailable.');
const replies = messages.filter((item) => item.role === 'assistant');
if (replies.length !== 1 || replies[0].id !== `${expected.turnId}-assistant`
    || !['complete', 'cancelled', 'error'].includes(replies[0].status)) {
  fail('The exact synthetic turn is missing or still active; cleanup was not attempted.');
}

const deletion = await request('DELETE', path);
if (deletion.deleted !== true || deletion.deletedTurns !== 1) {
  fail('The API did not confirm deletion of the exact synthetic bot and turn.');
}
console.log('Deleted the exact orphan release-test bot through its authenticated API.');
