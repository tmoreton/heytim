import { execFileSync } from 'child_process';
import type { AwsDeploymentTarget } from '@aws/agentcore-cdk';

const DEPLOY_STATE_PATH = 'agentcore/.cli/deployed-state.json';

type DeployedState = {
  targets?: Record<string, { resources?: unknown }>;
};

function foreignArnPaths(value: unknown, expectedAccount: string, path: string): string[] {
  if (typeof value === 'string') {
    const account = /^arn:[^:]+:[^:]*:[^:]*:(\d{12}):/.exec(value)?.[1];
    return account && account !== expectedAccount ? [`${path} (account ${account})`] : [];
  }
  if (Array.isArray(value)) {
    return value.flatMap((entry, index) => foreignArnPaths(entry, expectedAccount, `${path}[${index}]`));
  }
  if (value && typeof value === 'object') {
    return Object.entries(value).flatMap(([key, entry]) =>
      foreignArnPaths(entry, expectedAccount, path ? `${path}.${key}` : key)
    );
  }
  return [];
}

export function deployedStateAccountMismatches(
  deployedState: DeployedState | undefined,
  target: AwsDeploymentTarget
): string[] {
  const resources = deployedState?.targets?.[target.name]?.resources;
  return foreignArnPaths(resources, target.account, `targets.${target.name}.resources`);
}

export function assertDeployedStateMatchesTarget(
  deployedState: DeployedState | undefined,
  target: AwsDeploymentTarget
): void {
  const mismatches = deployedStateAccountMismatches(deployedState, target);
  if (mismatches.length === 0) return;

  throw new Error(
    `Refusing to synthesize ${target.name} for AWS account ${target.account}: ` +
      `agentcore/.cli/deployed-state.json still references another account at:\n${mismatches.join('\n')}\n` +
      'Reconcile or migrate the target state in a separately reviewed cutover before deploying.'
  );
}

export function dirtySourceEntries(status: string): string[] {
  return status
    .split('\n')
    .map(line => line.trimEnd())
    .filter(Boolean)
    .filter(line => {
      const path = line.slice(3).split(' -> ').at(-1);
      return path !== DEPLOY_STATE_PATH;
    });
}

export function assertCleanDeploySource(projectRoot: string): void {
  let status: string;
  try {
    status = execFileSync('git', ['status', '--porcelain=v1', '--untracked-files=all'], {
      cwd: projectRoot,
      encoding: 'utf8',
    });
  } catch (error) {
    throw new Error(
      `Deployment source must be a readable Git worktree: ${error instanceof Error ? error.message : error}`
    );
  }
  const dirty = dirtySourceEntries(status);
  if (dirty.length > 0) {
    throw new Error(
      `Refusing to deploy uncommitted source. Commit or remove these changes first:\n${dirty.join('\n')}`
    );
  }
}
