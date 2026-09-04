import { createHash } from 'node:crypto';

import {
  AdminGetUserCommand,
  CognitoIdentityProviderClient,
  UserNotFoundException,
} from '@aws-sdk/client-cognito-identity-provider';
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import { DynamoDBDocumentClient, GetCommand } from '@aws-sdk/lib-dynamodb';
import type { PreSignUpTriggerHandler } from 'aws-lambda';

const inviteKinds = new Set(['bot', 'chat', 'group', 'skill']);
const cognito = new CognitoIdentityProviderClient({});
const client = DynamoDBDocumentClient.from(new DynamoDBClient({}), {
  marshallOptions: { removeUndefinedValues: true },
});

const hashToken = (token: string): string => createHash('sha256').update(token).digest('hex');

const userAlreadyExists = async (userPoolId: string, username: string): Promise<boolean> => {
  try {
    await cognito.send(new AdminGetUserCommand({ UserPoolId: userPoolId, Username: username }));
    return true;
  } catch (value) {
    if (value instanceof UserNotFoundException) return false;
    throw value;
  }
};

export const handler: PreSignUpTriggerHandler = async (event) => {
  if (event.triggerSource !== 'PreSignUp_SignUp') return event;

  // Older app builds attempt sign-up before sign-in. Let Cognito return its
  // normal UsernameExistsException so those clients can continue to sign-in.
  const email = event.request.userAttributes.email?.trim().toLowerCase();
  if (email && (await userAlreadyExists(event.userPoolId, email))) return event;

  const tableName = process.env.INVITE_TABLE_NAME;
  const token = event.request.clientMetadata?.inviteToken?.trim();
  const kind = event.request.clientMetadata?.inviteKind?.trim();
  if (!tableName || !token || !kind || !inviteKinds.has(kind) || token.length > 128) {
    throw new Error('A valid FrogBot invitation is required to create an account.');
  }

  const { Item: invite } = await client.send(
    new GetCommand({
      TableName: tableName,
      Key: { tokenHash: hashToken(token) },
      ConsistentRead: true,
    }),
  );
  const now = Math.floor(Date.now() / 1000);
  if (!invite || invite.kind !== kind || typeof invite.expiresAt !== 'number' || invite.expiresAt < now) {
    throw new Error('This FrogBot invitation is invalid or has expired.');
  }

  return event;
};
