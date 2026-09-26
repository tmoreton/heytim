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
  publicApiFunction: LambdaFunction,
): void {
  const sharedEnvironment = {
    HEYTIM_FREE_MONTHLY_CREDITS: String(freeMonthlyCredits),
    HEYTIM_PLUS_MONTHLY_CREDITS: String(plusMonthlyCredits),
    HEYTIM_STRIPE_AVAILABLE: String(stripeAvailable),
  };
  for (const [name, value] of Object.entries(sharedEnvironment)) {
    for (const fn of [apiFunction, publicApiFunction]) fn.addEnvironment(name, value);
    workerFunction.addEnvironment(name, value);
  }
  for (const fn of [apiFunction, publicApiFunction]) {
    fn.addEnvironment('HEYTIM_PLUS_PRICE_CENTS', String(plusPriceCents));
    fn.addEnvironment('STRIPE_SECRET_ID', stripeSecretId);
    fn.addEnvironment('STRIPE_PLUS_PRICE_ID', stripePlusPriceId);
    fn.addEnvironment('STRIPE_LIVE_MODE', String(stripeLiveMode));
    fn.addEnvironment('STRIPE_AUTOMATIC_TAX', String(stripeAutomaticTax));
    fn.addEnvironment('STRIPE_API_VERSION', '2026-08-26.dahlia');
  }
  if (stripeSecretId) {
    const stack = Stack.of(apiFunction);
    const stripeSecretArn = stack.formatArn({
      service: 'secretsmanager',
      resource: 'secret',
      resourceName: `${stripeSecretId}-*`,
      arnFormat: ArnFormat.COLON_RESOURCE_NAME,
    });
    for (const fn of [apiFunction, publicApiFunction]) {
      fn.addToRolePolicy(
        new PolicyStatement({
          actions: ['secretsmanager:GetSecretValue'],
          resources: [stripeSecretArn],
        }),
      );
    }
  }
}
