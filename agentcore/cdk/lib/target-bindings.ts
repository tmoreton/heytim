import type { AgentCoreProjectSpec, AwsDeploymentTarget } from '@aws/agentcore-cdk';

export const UNCONFIGURED_AWS_ACCOUNT = '000000000000';

export function filesBucketName(target: AwsDeploymentTarget): string {
  const prefix = target.name === 'production' ? 'frogbot-production-user-files' : 'frogbot-user-files';
  return `${prefix}-${target.account}-${target.region}`;
}

export function filesKeyAlias(target: AwsDeploymentTarget): string {
  return target.name === 'production' ? 'alias/frogbot-production-user-files' : 'alias/frogbot-user-files';
}

export function bindSpecToTarget(
  source: AgentCoreProjectSpec,
  target: AwsDeploymentTarget,
  productionMemoryKeyArn = process.env.FROGBOT_AGENTCORE_MEMORY_KMS_KEY_ARN?.trim()
): AgentCoreProjectSpec {
  // The JSON remains the behavioral source of truth. This copy only resolves
  // account/Region-specific infrastructure values that cannot be shared by
  // independent deployment targets.
  const spec = JSON.parse(JSON.stringify(source)) as AgentCoreProjectSpec;
  // Published schema types can lag fields already supported by the CLI/L3.
  // Keep the compatibility cast at this target-binding boundary.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mutable = spec as any;

  for (const runtime of mutable.runtimes ?? []) {
    const bucket = filesBucketName(target);
    const existing = (runtime.envVars ?? []).find((item: { name?: string }) => item.name === 'FROGBOT_FILES_BUCKET');
    if (existing) existing.value = bucket;
    else (runtime.envVars ??= []).push({ name: 'FROGBOT_FILES_BUCKET', value: bucket });

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

export function assertProductionTargetConfigured(targets: AwsDeploymentTarget[]): AwsDeploymentTarget {
  const development = targets.find(target => target.name === 'development');
  const production = targets.find(target => target.name === 'production');
  if (!development || !production) {
    throw new Error('Both development and production AWS deployment targets are required.');
  }
  if (production.account === UNCONFIGURED_AWS_ACCOUNT) {
    throw new Error('Replace the production AWS account placeholder before release.');
  }
  if (production.account === development.account) {
    throw new Error('Production must use a different AWS account from development.');
  }
  return production;
}
