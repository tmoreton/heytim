import type { AgentCoreProjectSpec, AwsDeploymentTarget } from '@aws/agentcore-cdk';

export const UNCONFIGURED_AWS_ACCOUNT = '000000000000';

export function filesBucketName(target: AwsDeploymentTarget): string {
  const prefix = target.name === 'production' ? 'heytim-production-user-files' : 'heytim-user-files';
  return `${prefix}-${target.account}-${target.region}`;
}

export function filesKeyAlias(target: AwsDeploymentTarget): string {
  return target.name === 'production' ? 'alias/heytim-production-user-files' : 'alias/heytim-user-files';
}

export function bindSpecToTarget(
  source: AgentCoreProjectSpec,
  target: AwsDeploymentTarget,
  productionMemoryKeyArn = process.env.HEYTIM_AGENTCORE_MEMORY_KMS_KEY_ARN?.trim(),
  sharedProductionAccount = false
): AgentCoreProjectSpec {
  // The JSON remains the behavioral source of truth. This copy only resolves
  // account/Region-specific infrastructure values that cannot be shared by
  // independent deployment targets.
  const spec = JSON.parse(JSON.stringify(source)) as AgentCoreProjectSpec;
  // Published schema types can lag fields already supported by the CLI/L3.
  // Keep the compatibility cast at this target-binding boundary.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mutable = spec as any;

  // AgentCore service names are account/Region scoped and the L3 derives them
  // from the project name. Give a temporary same-account production target a
  // separate physical namespace without changing the authoritative JSON names.
  if (target.name === 'production' && sharedProductionAccount) {
    mutable.name = `${mutable.name}Production`;
  }

  for (const runtime of mutable.runtimes ?? []) {
    const bucket = filesBucketName(target);
    const existing = (runtime.envVars ?? []).find((item: { name?: string }) => item.name === 'HEYTIM_FILES_BUCKET');
    if (existing) existing.value = bucket;
    else (runtime.envVars ??= []).push({ name: 'HEYTIM_FILES_BUCKET', value: bucket });

    // attachments-policy.json documents the local/default target contract.
    // The stack installs its target-scoped equivalent to avoid hardcoded
    // development ARNs in production execution roles.
    runtime.additionalPolicies = (runtime.additionalPolicies ?? []).filter(
      (entry: string) => entry !== 'attachments-policy.json'
    );
  }

  if (target.name === 'production') {
    for (const memory of mutable.memories ?? []) {
      if (productionMemoryKeyArn) memory.encryptionKeyArn = productionMemoryKeyArn;
      else delete memory.encryptionKeyArn;
    }
  }

  return spec;
}

export function assertProductionTargetConfigured(
  targets: AwsDeploymentTarget[],
  allowSharedAccount = process.env.HEYTIM_ALLOW_SHARED_PRODUCTION_ACCOUNT === 'true'
): AwsDeploymentTarget {
  const development = targets.find(target => target.name === 'development');
  const production = targets.find(target => target.name === 'production');
  if (!development || !production) {
    throw new Error('Both development and production AWS deployment targets are required.');
  }
  if (production.account === UNCONFIGURED_AWS_ACCOUNT) {
    throw new Error('Replace the production AWS account placeholder before release.');
  }
  if (production.account === development.account && !allowSharedAccount) {
    throw new Error(
      'Production must use a different AWS account from development unless HEYTIM_ALLOW_SHARED_PRODUCTION_ACCOUNT=true.'
    );
  }
  return production;
}
