import { ArnFormat, Stack } from 'aws-cdk-lib';
import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import type { Function as LambdaFunction } from 'aws-cdk-lib/aws-lambda';
import locations from '../functions/shared/static_credential_locations.json';

/** Preserve credential identifiers while granting access only to their reviewed parameters. */
export function addStaticCredentialAccess(fn: LambdaFunction, identifiers: string[]) {
  const paths = [...new Set(locations
    .filter(row => identifiers.includes(row.sourceArn) || identifiers.includes(row.sourceName))
    .map(row => row.parameterArn.split(':parameter/')[1]))];
  if (!paths.length) return;
  const stack = Stack.of(fn);
  fn.addEnvironment('HEYTIM_CREDENTIAL_ACCOUNT_ID', stack.account);
  fn.addToRolePolicy(new PolicyStatement({
    actions: ['ssm:GetParameter'],
    resources: paths.map(resourceName => stack.formatArn({
      service: 'ssm', resource: 'parameter', resourceName,
      arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
    })),
  }));
}
