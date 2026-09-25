import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { Function as LambdaFunction } from 'aws-cdk-lib/aws-lambda';

type ProviderSecrets = {
  github: string;
  google: string;
  hubspot: string;
  jira: string;
  microsoft: string;
  notion: string;
  plaid: string;
  quickbooks: string;
  slack: string;
  x: string;
  zoom: string;
};

const providerIdsBySecret: Record<keyof ProviderSecrets, string[]> = {
  github: ['github'],
  google: ['gmail', 'youtube', 'google_workspace'],
  hubspot: ['hubspot'],
  jira: ['jira'],
  microsoft: ['microsoft', 'microsoft_teams'],
  notion: ['notion'],
  plaid: ['plaid'],
  quickbooks: ['quickbooks'],
  slack: ['slack'],
  x: ['x'],
  zoom: ['zoom'],
};

export function addProviderConnectionAccess(
  apiFunction: LambdaFunction,
  apiEndpoint: string,
  secrets: ProviderSecrets,
): void {
  apiFunction.addEnvironment('GOOGLE_OAUTH_SECRET_ARN', secrets.google);
  apiFunction.addEnvironment('HUBSPOT_OAUTH_SECRET_ARN', secrets.hubspot);
  apiFunction.addEnvironment('JIRA_OAUTH_SECRET_ARN', secrets.jira);
  apiFunction.addEnvironment('GITHUB_APP_SECRET_ARN', secrets.github);
  apiFunction.addEnvironment('X_OAUTH_SECRET_ARN', secrets.x);
  apiFunction.addEnvironment('SLACK_OAUTH_SECRET_ARN', secrets.slack);
  apiFunction.addEnvironment('MICROSOFT_OAUTH_SECRET_ARN', secrets.microsoft);
  apiFunction.addEnvironment('NOTION_OAUTH_SECRET_ARN', secrets.notion);
  apiFunction.addEnvironment('ZOOM_OAUTH_SECRET_ARN', secrets.zoom);
  apiFunction.addEnvironment('QUICKBOOKS_OAUTH_SECRET_ARN', secrets.quickbooks);
  apiFunction.addEnvironment('PLAID_SECRET_ARN', secrets.plaid);
  const disabledProviders = (Object.keys(providerIdsBySecret) as Array<keyof ProviderSecrets>)
    .filter((provider) => secrets[provider].length === 0)
    .flatMap((provider) => providerIdsBySecret[provider]);
  apiFunction.addEnvironment(
    'DISABLED_CONNECTION_PROVIDER_IDS',
    disabledProviders.join(','),
  );
  apiFunction.addEnvironment(
    'GOOGLE_OAUTH_REDIRECT_URI',
    `${apiEndpoint}/public/oauth/google/callback`,
  );
  apiFunction.addEnvironment(
    'GITHUB_OAUTH_REDIRECT_URI',
    `${apiEndpoint}/public/oauth/github/callback`,
  );
  apiFunction.addEnvironment(
    'X_OAUTH_REDIRECT_URI',
    `${apiEndpoint}/public/oauth/x/callback`,
  );
  apiFunction.addEnvironment(
    'EXTERNAL_OAUTH_REDIRECT_URI',
    apiEndpoint + '/public/oauth/provider/callback',
  );
  apiFunction.addEnvironment(
    'QUICKBOOKS_OAUTH_REDIRECT_URI',
    apiEndpoint + '/public/oauth/quickbooks/callback',
  );
  apiFunction.addEnvironment(
    'PLAID_COMPLETION_REDIRECT_URI',
    apiEndpoint + '/public/plaid/callback',
  );
  apiFunction.addEnvironment('PLAID_OAUTH_REDIRECT_URI', 'https://heytim.ai/plaid-oauth');
  const configuredSecrets = Object.values(secrets).filter((value) => value.length > 0);
  if (configuredSecrets.length) {
    apiFunction.addToRolePolicy(new PolicyStatement({
      actions: ['secretsmanager:GetSecretValue'],
      resources: configuredSecrets,
    }));
  }
}
