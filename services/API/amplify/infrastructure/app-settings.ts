export const PUBLIC_WEB_BASE_URL = 'https://froggybot.com';
export const CAPABILITY_CATALOG_URL = `${PUBLIC_WEB_BASE_URL}/catalog.json`;
export const deploymentEnvironment = process.env.FROGBOT_ENVIRONMENT ?? 'development';
if (!/^[a-z][a-z0-9-]{0,20}$/.test(deploymentEnvironment)) {
  throw new Error('FROGBOT_ENVIRONMENT must be a short lowercase environment name.');
}

const PRODUCTION_WEB_ORIGINS = [
  PUBLIC_WEB_BASE_URL,
  'https://app.froggybot.com',
  'https://www.froggybot.com',
  'https://frogbot.expo.app',
];
export const ALLOWED_WEB_ORIGINS = deploymentEnvironment === 'production'
  ? PRODUCTION_WEB_ORIGINS
  : [...PRODUCTION_WEB_ORIGINS, 'http://localhost:8081', 'http://localhost:19006'];
export const FUNCTION_ASSET_EXCLUDES = [
  'tests/**',
  '**/__pycache__/**',
  '**/*.pyc',
  '.pytest_cache/**',
  '.ruff_cache/**',
];
export const WORKER_CONCURRENCY = 10;

function boundedIntegerSetting(
  name: string,
  defaultValue: number,
  minimum: number,
  maximum: number,
  requiredInProduction = false,
): number {
  const raw = process.env[name];
  if (raw === undefined) {
    if (requiredInProduction && deploymentEnvironment === 'production') {
      throw new Error(`${name} must be set before deploying production.`);
    }
    return defaultValue;
  }
  if (!/^\d+$/.test(raw)) {
    throw new Error(`${name} must be a whole number.`);
  }
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${name} must be between ${minimum} and ${maximum}.`);
  }
  return value;
}

function requiredSetting(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Set ${name} before running an Amplify sandbox or deploy.`);
  }
  return value;
}

function stagedProviderSetting(name: string): string {
  const value = process.env[name]?.trim() ?? '';
  if ((process.env.FROGBOT_ENVIRONMENT ?? 'development') === 'production' && !value) {
    throw new Error(name + ' must be set before deploying production.');
  }
  return value;
}

function optionalProviderSetting(name: string): string {
  return process.env[name]?.trim() ?? '';
}

function optionalPlatformApplicationArn(name: string): string {
  const value = process.env[name]?.trim() ?? '';
  if (value && !/^arn:aws[a-zA-Z-]*:sns:[a-z0-9-]+:\d{12}:app\/APNS(?:_SANDBOX)?\/[A-Za-z0-9_.-]+$/.test(value)) {
    throw new Error(`${name} must be an SNS APNs platform application ARN.`);
  }
  return value;
}

export const monthlyRunUnitLimit = boundedIntegerSetting(
  'FROGBOT_MONTHLY_RUN_UNIT_LIMIT', 1_000, 1, 1_000_000,
);
export const userWindowRunUnitLimit = boundedIntegerSetting(
  'FROGBOT_USER_WINDOW_RUN_UNIT_LIMIT', 30, 1, 10_000,
);
export const globalWindowRunUnitLimit = boundedIntegerSetting(
  'FROGBOT_GLOBAL_WINDOW_RUN_UNIT_LIMIT', 300, 1, 100_000,
);
export const usageWindowSeconds = boundedIntegerSetting(
  'FROGBOT_USAGE_WINDOW_SECONDS', 60, 10, 3_600,
);
export const youtubeSearchDailyLimit = boundedIntegerSetting(
  'FROGBOT_YOUTUBE_SEARCH_DAILY_LIMIT', 100, 3, 1_000_000, true,
);

export const runtimeArn = requiredSetting('FROGBOT_AGENT_RUNTIME_ARN');
export const runtimeQualifier = process.env.FROGBOT_AGENT_RUNTIME_QUALIFIER ?? 'DEFAULT';
if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$/.test(runtimeQualifier)) {
  throw new Error('FROGBOT_AGENT_RUNTIME_QUALIFIER is invalid.');
}
export const memoryId = requiredSetting('FROGBOT_MEMORY_ID');
export const memoryKmsKeyArn = requiredSetting('FROGBOT_AGENTCORE_MEMORY_KMS_KEY_ARN');
export const googleOAuthSecretArn = requiredSetting('FROGBOT_GOOGLE_OAUTH_SECRET_ARN');
export const githubAppSecretArn = requiredSetting('FROGBOT_GITHUB_APP_SECRET_ARN');
export const xOAuthSecretArn = requiredSetting('FROGBOT_X_OAUTH_SECRET_ARN');
export const slackOAuthSecretArn = stagedProviderSetting('FROGBOT_SLACK_OAUTH_SECRET_ARN');
export const microsoftOAuthSecretArn = optionalProviderSetting('FROGBOT_MICROSOFT_OAUTH_SECRET_ARN');
export const notionOAuthSecretArn = stagedProviderSetting('FROGBOT_NOTION_OAUTH_SECRET_ARN');
export const hubspotOAuthSecretArn = optionalProviderSetting('FROGBOT_HUBSPOT_OAUTH_SECRET_ARN');
export const jiraOAuthSecretArn = optionalProviderSetting('FROGBOT_JIRA_OAUTH_SECRET_ARN');
export const zoomOAuthSecretArn = optionalProviderSetting('FROGBOT_ZOOM_OAUTH_SECRET_ARN');
export const apnsApplicationArn = optionalPlatformApplicationArn('FROGBOT_APNS_APPLICATION_ARN');
export const apnsSandboxApplicationArn = optionalPlatformApplicationArn('FROGBOT_APNS_SANDBOX_APPLICATION_ARN');
if (deploymentEnvironment === 'production' && !apnsApplicationArn) {
  throw new Error('Set FROGBOT_APNS_APPLICATION_ARN before deploying production.');
}
if (deploymentEnvironment === 'production' && !process.env.FROGBOT_MONTHLY_BUDGET_USD) {
  throw new Error('FROGBOT_MONTHLY_BUDGET_USD must be set before deploying production.');
}
export const monthlyBudgetUsd = Number(process.env.FROGBOT_MONTHLY_BUDGET_USD ?? '100');
if (!Number.isFinite(monthlyBudgetUsd) || monthlyBudgetUsd <= 0) {
  throw new Error('FROGBOT_MONTHLY_BUDGET_USD must be a positive number.');
}
