import assert from 'node:assert/strict';
import { createHash, generateKeyPairSync, sign } from 'node:crypto';
import test from 'node:test';

import { verifyPlaidWebhook } from './handler';

const { privateKey, publicKey } = generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
const config = { clientId: 'client-id', secret: 'secret', environment: 'sandbox' };
const getKey = async () => publicKey.export({ format: 'jwk' });

function signed(body: Buffer, issuedAt = Math.floor(Date.now() / 1000)): string {
  const header = Buffer.from(JSON.stringify({ alg: 'ES256', kid: 'test-key' })).toString('base64url');
  const payload = Buffer.from(JSON.stringify({
    iat: issuedAt,
    request_body_sha256: createHash('sha256').update(body).digest('hex'),
  })).toString('base64url');
  const input = `${header}.${payload}`;
  const signature = sign('sha256', Buffer.from(input), {
    key: privateKey, dsaEncoding: 'ieee-p1363',
  }).toString('base64url');
  return `${input}.${signature}`;
}

test('accepts only correctly signed, fresh, exact Plaid webhook bodies', async () => {
  const body = Buffer.from('{"webhook_type":"TRANSACTIONS","item_id":"item_12345678"}');
  const jwt = signed(body);
  assert.equal(await verifyPlaidWebhook(jwt, body, config, getKey), true);
  assert.equal(await verifyPlaidWebhook(jwt, Buffer.from('{}'), config, getKey), false);
  assert.equal(await verifyPlaidWebhook(signed(body, 1000), body, config, getKey), false);
  assert.equal(await verifyPlaidWebhook(jwt.slice(0, -2) + 'AA', body, config, getKey), false);
});
