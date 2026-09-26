import { createHash, createPublicKey, timingSafeEqual, verify, type JsonWebKey } from 'node:crypto';
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import { DynamoDBDocumentClient, GetCommand } from '@aws-sdk/lib-dynamodb';
import { GetSecretValueCommand, SecretsManagerClient } from '@aws-sdk/client-secrets-manager';
import { SendMessageCommand, SQSClient } from '@aws-sdk/client-sqs';
import type { APIGatewayProxyEventV2, APIGatewayProxyResultV2 } from 'aws-lambda';

const region = process.env.AWS_REGION;
const table = DynamoDBDocumentClient.from(new DynamoDBClient({ region, maxAttempts: 3 }));
const secrets = new SecretsManagerClient({ region, maxAttempts: 3 });
const sqs = new SQSClient({ region, maxAttempts: 3 });
const plaidUrls: Record<string, string> = {
  sandbox: 'https://sandbox.plaid.com',
  production: 'https://production.plaid.com',
};

type PlaidConfig = { clientId: string; secret: string; environment: string };
let cachedConfig: { value: PlaidConfig; expiresAt: number } | undefined;
const keyCache = new Map<string, { key: JsonWebKey; expiresAt: number }>();

function decodedJson(part: string): Record<string, unknown> {
  if (!/^[A-Za-z0-9_-]+$/.test(part) || part.length > 10000) throw new Error('Invalid JWT');
  const value: unknown = JSON.parse(Buffer.from(part, 'base64url').toString('utf8'));
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid JWT');
  return value as Record<string, unknown>;
}

async function configuration(): Promise<PlaidConfig> {
  if (cachedConfig && cachedConfig.expiresAt > Date.now()) return cachedConfig.value;
  const arn = process.env.PLAID_SECRET_ARN;
  if (!arn) throw new Error('Plaid is not configured');
  const value = await secrets.send(new GetSecretValueCommand({ SecretId: arn }));
  const config: unknown = JSON.parse(value.SecretString ?? '{}');
  if (!config || typeof config !== 'object') throw new Error('Plaid is not configured');
  const fields = config as Record<string, unknown>;
  if (typeof fields.clientId !== 'string' || typeof fields.secret !== 'string'
      || typeof fields.environment !== 'string' || !plaidUrls[fields.environment]) {
    throw new Error('Plaid is not configured');
  }
  cachedConfig = { value: fields as PlaidConfig, expiresAt: Date.now() + 10 * 60 * 1000 };
  return cachedConfig.value;
}

async function verificationKey(config: PlaidConfig, keyId: string): Promise<JsonWebKey> {
  const cached = keyCache.get(keyId);
  if (cached && cached.expiresAt > Date.now()) return cached.key;
  const response = await fetch(`${plaidUrls[config.environment]}/webhook_verification_key/get`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ client_id: config.clientId, secret: config.secret, key_id: keyId }),
    signal: AbortSignal.timeout(8000),
  });
  if (!response.ok) throw new Error('Plaid verification key unavailable');
  const data: unknown = await response.json();
  const key = (data as { key?: JsonWebKey })?.key;
  if (!key || key.kty !== 'EC' || key.crv !== 'P-256' || typeof key.x !== 'string'
      || typeof key.y !== 'string') throw new Error('Invalid Plaid verification key');
  keyCache.set(keyId, { key, expiresAt: Date.now() + 60 * 60 * 1000 });
  return key;
}

export async function verifyPlaidWebhook(
  jwt: string, rawBody: Buffer, config: PlaidConfig,
  getKey: typeof verificationKey = verificationKey,
): Promise<boolean> {
  if (jwt.length > 12000) return false;
  try {
    const parts = jwt.split('.');
    if (parts.length !== 3) return false;
    const header = decodedJson(parts[0]);
    const claims = decodedJson(parts[1]);
    if (header.alg !== 'ES256' || typeof header.kid !== 'string'
        || !/^[A-Za-z0-9_-]{1,200}$/.test(header.kid)) return false;
    const now = Math.floor(Date.now() / 1000);
    if (typeof claims.iat !== 'number' || !Number.isInteger(claims.iat)
        || claims.iat > now + 30 || claims.iat < now - 300) return false;
    if (typeof claims.request_body_sha256 !== 'string'
        || !/^[a-f0-9]{64}$/.test(claims.request_body_sha256)) return false;
    const expected = createHash('sha256').update(rawBody).digest();
    if (!timingSafeEqual(expected, Buffer.from(claims.request_body_sha256, 'hex'))) return false;
    const key = createPublicKey({ key: await getKey(config, header.kid), format: 'jwk' });
    const signature = Buffer.from(parts[2], 'base64url');
    return verify('sha256', Buffer.from(`${parts[0]}.${parts[1]}`),
      { key, dsaEncoding: 'ieee-p1363' }, signature);
  } catch {
    return false;
  }
}

export const handler = async (event: APIGatewayProxyEventV2): Promise<APIGatewayProxyResultV2> => {
  const raw = event.isBase64Encoded
    ? Buffer.from(event.body ?? '', 'base64') : Buffer.from(event.body ?? '', 'utf8');
  if (raw.length > 256_000) return { statusCode: 413 };
  const header = Object.entries(event.headers).find(
    ([name]) => name.toLowerCase() === 'plaid-verification',
  )?.[1];
  if (!header || !(await verifyPlaidWebhook(header, raw, await configuration()))) {
    return { statusCode: 401 };
  }
  let webhook: Record<string, unknown>;
  try {
    webhook = JSON.parse(raw.toString('utf8')) as Record<string, unknown>;
  } catch {
    return { statusCode: 400 };
  }
  if (webhook.webhook_type !== 'TRANSACTIONS'
      || !['SYNC_UPDATES_AVAILABLE', 'INITIAL_UPDATE', 'HISTORICAL_UPDATE', 'DEFAULT_UPDATE']
        .includes(String(webhook.webhook_code))) return { statusCode: 200 };
  if (typeof webhook.item_id !== 'string' || !/^[A-Za-z0-9_-]{8,200}$/.test(webhook.item_id)) {
    return { statusCode: 400 };
  }
  const config = await configuration();
  const mapping = await table.send(new GetCommand({
    TableName: process.env.TABLE_NAME,
    Key: { pk: `PLAID_ITEM#${config.environment}#${webhook.item_id}`, sk: 'CONNECTION' },
    ConsistentRead: true,
  }));
  const userId = mapping.Item?.userId;
  const connectionId = mapping.Item?.connectionId;
  if (typeof userId !== 'string' || typeof connectionId !== 'string') return { statusCode: 200 };
  await sqs.send(new SendMessageCommand({
    QueueUrl: process.env.QUEUE_URL,
    MessageBody: JSON.stringify({
      type: 'PLAID_SYNC', userId, connectionId,
      historicalComplete: webhook.webhook_code === 'HISTORICAL_UPDATE',
    }),
  }));
  return { statusCode: 200 };
};
