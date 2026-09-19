import { ArnFormat, Stack } from 'aws-cdk-lib';
import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { Function as LambdaFunction } from 'aws-cdk-lib/aws-lambda';

import {
  freeMonthlyCredits,
  plusMonthlyCredits,
  plusPriceCents,
  stripeAutomaticTax,
  stripeAvailable,
  stripeLiveMode,
  stripePlusPriceId,
  stripeSecretId,
} from './app-settings';

export function addStripeBilling(
  apiFunction: LambdaFunction,
  workerFunction: LambdaFunction,
): void {
  const sharedEnvironment = {
    HEYTIM_FREE_MONTHLY_CREDITS: String(freeMonthlyCredits),
    HEYTIM_PLUS_MONTHLY_CREDITS: String(plusMonthlyCredits),
    HEYTIM_STRIPE_AVAILABLE: String(stripeAvailable),
  };
  for (const [name, value] of Object.entries(sharedEnvironment)) {
    apiFunction.addEnvironment(name, value);
    workerFunction.addEnvironment(name, value);
  }
  apiFunction.addEnvironment('HEYTIM_PLUS_PRICE_CENTS', String(plusPriceCents));
  apiFunction.addEnvironment('STRIPE_SECRET_ID', stripeSecretId);
  apiFunction.addEnvironment('STRIPE_PLUS_PRICE_ID', stripePlusPriceId);
  apiFunction.addEnvironment('STRIPE_LIVE_MODE', String(stripeLiveMode));
  apiFunction.addEnvironment('STRIPE_AUTOMATIC_TAX', String(stripeAutomaticTax));
  apiFunction.addEnvironment('STRIPE_API_VERSION', '2026-08-26.dahlia');
  if (stripeSecretId) {
    const stack = Stack.of(apiFunction);
    const stripeSecretArn = stack.formatArn({
      service: 'secretsmanager',
      resource: 'secret',
      resourceName: `${stripeSecretId}-*`,
      arnFormat: ArnFormat.COLON_RESOURCE_NAME,
    });
    apiFunction.addToRolePolicy(
      new PolicyStatement({
        actions: ['secretsmanager:GetSecretValue'],
        resources: [stripeSecretArn],
      }),
    );
  }
}
