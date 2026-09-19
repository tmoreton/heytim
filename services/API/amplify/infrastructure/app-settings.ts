export const PUBLIC_WEB_BASE_URL = 'https://heytim.ai';
export const CAPABILITY_CATALOG_URL = `${PUBLIC_WEB_BASE_URL}/catalog.json`;
export const deploymentEnvironment = process.env.HEYTIM_ENVIRONMENT ?? 'development';
if (!/^[a-z][a-z0-9-]{0,20}$/.test(deploymentEnvironment)) {
  throw new Error('HEYTIM_ENVIRONMENT must be a short lowercase environment name.');
}

const PRODUCTION_WEB_ORIGINS = [
  PUBLIC_WEB_BASE_URL,
  'https://www.heytim.ai',
  'https://heytim.expo.app',
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
  if ((process.env.HEYTIM_ENVIRONMENT ?? 'development') === 'production' && !value) {
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
  'HEYTIM_MONTHLY_RUN_UNIT_LIMIT', 1_000, 1, 1_000_000,
);
export const userWindowRunUnitLimit = boundedIntegerSetting(
  'HEYTIM_USER_WINDOW_RUN_UNIT_LIMIT', 30, 1, 10_000,
);
export const globalWindowRunUnitLimit = boundedIntegerSetting(
  'HEYTIM_GLOBAL_WINDOW_RUN_UNIT_LIMIT', 300, 1, 100_000,
);
export const usageWindowSeconds = boundedIntegerSetting(
  'HEYTIM_USAGE_WINDOW_SECONDS', 60, 10, 3_600,
);
export const youtubeSearchDailyLimit = boundedIntegerSetting(
  'HEYTIM_YOUTUBE_SEARCH_DAILY_LIMIT', 100, 3, 1_000_000, true,
);
export const freeMonthlyCredits = boundedIntegerSetting(
  'HEYTIM_FREE_MONTHLY_CREDITS', 30, 1, 1_000_000,
);
export const plusMonthlyCredits = boundedIntegerSetting(
  'HEYTIM_PLUS_MONTHLY_CREDITS', 300, 1, 1_000_000,
);
export const plusPriceCents = boundedIntegerSetting(
  'HEYTIM_PLUS_PRICE_CENTS', 2_000, 1, 10_000_000,
);
if (freeMonthlyCredits > monthlyRunUnitLimit || plusMonthlyCredits > monthlyRunUnitLimit) {
  throw new Error('Plan credits cannot exceed HEYTIM_MONTHLY_RUN_UNIT_LIMIT.');
}

export const stripeSecretArn = optionalProviderSetting('HEYTIM_STRIPE_SECRET_ARN');
export const stripePlusPriceId = optionalProviderSetting('HEYTIM_STRIPE_PLUS_PRICE_ID');
if (Boolean(stripeSecretArn) !== Boolean(stripePlusPriceId)) {
  throw new Error('HEYTIM_STRIPE_SECRET_ARN and HEYTIM_STRIPE_PLUS_PRICE_ID must be set together.');
}
if (stripeSecretArn && !stripeSecretArn.startsWith('arn:aws:secretsmanager:')) {
  throw new Error('HEYTIM_STRIPE_SECRET_ARN must be an AWS Secrets Manager ARN.');
}
if (stripePlusPriceId && !/^price_[A-Za-z0-9]+$/.test(stripePlusPriceId)) {
  throw new Error('HEYTIM_STRIPE_PLUS_PRICE_ID must be a Stripe Price ID.');
}
const stripeLiveModeValue = process.env.HEYTIM_STRIPE_LIVE_MODE ?? 'false';
if (!['true', 'false'].includes(stripeLiveModeValue)) {
  throw new Error('HEYTIM_STRIPE_LIVE_MODE must be true or false.');
}
export const stripeLiveMode = stripeLiveModeValue === 'true';
const stripeAutomaticTaxValue = process.env.HEYTIM_STRIPE_AUTOMATIC_TAX ?? 'false';
if (!['true', 'false'].includes(stripeAutomaticTaxValue)) {
  throw new Error('HEYTIM_STRIPE_AUTOMATIC_TAX must be true or false.');
}
export const stripeAutomaticTax = stripeAutomaticTaxValue === 'true';
export const stripeAvailable = Boolean(stripeSecretArn && stripePlusPriceId);
if (stripeLiveMode && !stripeAvailable) {
  throw new Error('Stripe must be configured before enabling live mode.');
}

export const runtimeArn = requiredSetting('HEYTIM_AGENT_RUNTIME_ARN');
export const runtimeQualifier = process.env.HEYTIM_AGENT_RUNTIME_QUALIFIER ?? 'DEFAULT';
if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$/.test(runtimeQualifier)) {
  throw new Error('HEYTIM_AGENT_RUNTIME_QUALIFIER is invalid.');
}
export const memoryId = requiredSetting('HEYTIM_MEMORY_ID');
export const memoryKmsKeyArn = requiredSetting('HEYTIM_AGENTCORE_MEMORY_KMS_KEY_ARN');
export const googleOAuthSecretArn = requiredSetting('HEYTIM_GOOGLE_OAUTH_SECRET_ARN');
export const githubAppSecretArn = requiredSetting('HEYTIM_GITHUB_APP_SECRET_ARN');
export const xOAuthSecretArn = requiredSetting('HEYTIM_X_OAUTH_SECRET_ARN');
export const slackOAuthSecretArn = stagedProviderSetting('HEYTIM_SLACK_OAUTH_SECRET_ARN');
export const microsoftOAuthSecretArn = optionalProviderSetting('HEYTIM_MICROSOFT_OAUTH_SECRET_ARN');
export const notionOAuthSecretArn = stagedProviderSetting('HEYTIM_NOTION_OAUTH_SECRET_ARN');
export const hubspotOAuthSecretArn = optionalProviderSetting('HEYTIM_HUBSPOT_OAUTH_SECRET_ARN');
export const jiraOAuthSecretArn = optionalProviderSetting('HEYTIM_JIRA_OAUTH_SECRET_ARN');
export const zoomOAuthSecretArn = optionalProviderSetting('HEYTIM_ZOOM_OAUTH_SECRET_ARN');
export const apnsApplicationArn = optionalPlatformApplicationArn('HEYTIM_APNS_APPLICATION_ARN');
export const apnsSandboxApplicationArn = optionalPlatformApplicationArn('HEYTIM_APNS_SANDBOX_APPLICATION_ARN');
if (deploymentEnvironment === 'production' && !apnsApplicationArn) {
  throw new Error('Set HEYTIM_APNS_APPLICATION_ARN before deploying production.');
}
if (deploymentEnvironment === 'production' && !process.env.HEYTIM_MONTHLY_BUDGET_USD) {
  throw new Error('HEYTIM_MONTHLY_BUDGET_USD must be set before deploying production.');
}
export const monthlyBudgetUsd = Number(process.env.HEYTIM_MONTHLY_BUDGET_USD ?? '100');
if (!Number.isFinite(monthlyBudgetUsd) || monthlyBudgetUsd <= 0) {
  throw new Error('HEYTIM_MONTHLY_BUDGET_USD must be a positive number.');
}
