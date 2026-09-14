import { execFileSync } from 'child_process';

const DEPLOY_STATE_PATH = 'agentcore/.cli/deployed-state.json';

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
