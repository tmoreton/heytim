import { GetParameterCommand, SSMClient } from '@aws-sdk/client-ssm';
import { GetSecretValueCommand, SecretsManagerClient } from '@aws-sdk/client-secrets-manager';
import locations from './static_credential_locations.json';

const region = process.env.AWS_REGION;
const parameters = new SSMClient({ region, maxAttempts: 3 });
const secrets = new SecretsManagerClient({ region, maxAttempts: 3 });
const parameterBySecret = new Map(locations.map(row => [row.sourceArn, row.parameterArn]));

export async function readStaticCredential(identifier: string): Promise<string> {
  const parameter = parameterBySecret.get(identifier);
  if (parameter) {
    const value = await parameters.send(new GetParameterCommand({ Name: parameter, WithDecryption: true }));
    if (typeof value.Parameter?.Value !== 'string') throw new Error('Credential parameter is unavailable');
    return value.Parameter.Value;
  }
  const value = await secrets.send(new GetSecretValueCommand({ SecretId: identifier }));
  return value.SecretString ?? '';
}
