import { Stack, Token } from 'aws-cdk-lib';
import { Bucket } from 'aws-cdk-lib/aws-s3';
import type { IBucket } from 'aws-cdk-lib/aws-s3';
import type { ITopic } from 'aws-cdk-lib/aws-sns';

import { addBotEmailCapture } from './bot-email-capture';
import { addBotEmailQuarantine } from './bot-email-quarantine';

const DESTINATION_ACCOUNT = '820323452649';

export function validatedStandaloneCaptureBucket(
  stack: Stack,
  stage: string | undefined,
  bucketName: string | undefined,
): string | undefined {
  const value = bucketName?.trim();
  if (value && stage !== 'receive') {
    throw new Error('The standalone mail capture bucket requires the receive stage.');
  }
  if (stage !== 'receive') return undefined;

  // Amplify can leave a nested stack's account as ${AWS::AccountId} at synth
  // time. The private preview verifies STS before setting CDK_DEFAULT_ACCOUNT.
  const account = Token.isUnresolved(stack.account)
    ? process.env.CDK_DEFAULT_ACCOUNT?.trim()
    : stack.account;
  if (!account || !/^\d{12}$/.test(account)) {
    throw new Error('A resolved AWS account is required for mail receiving.');
  }
  if (account === DESTINATION_ACCOUNT && !value) {
    throw new Error('Destination mail receiving requires the standalone capture bucket.');
  }
  if (value && (
    account !== DESTINATION_ACCOUNT
    || !/^heytimdestinationmailcapt-botemailquarantine[a-z0-9-]+$/.test(value)
  )) {
    throw new Error('The standalone mail capture bucket must belong to the destination stack.');
  }
  return value;
}

/** Keep one capture owner when the standalone destination stack is deployed. */
export function botEmailCaptureOwner(
  stack: Stack,
  topic: ITopic,
  standaloneBucketName?: string,
): { quarantine: IBucket; standalone: boolean } {
  if (standaloneBucketName) {
    return {
      quarantine: Bucket.fromBucketName(
        stack, 'StandaloneBotEmailQuarantine', standaloneBucketName,
      ),
      standalone: true,
    };
  }
  addBotEmailCapture(stack, topic);
  return { quarantine: addBotEmailQuarantine(stack), standalone: false };
}
