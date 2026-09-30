import { Stack } from 'aws-cdk-lib';
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
  if (stage === 'receive' && stack.account === DESTINATION_ACCOUNT && !value) {
    throw new Error('Destination mail receiving requires the standalone capture bucket.');
  }
  if (value && (
    stage !== 'receive'
    || stack.account !== DESTINATION_ACCOUNT
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
