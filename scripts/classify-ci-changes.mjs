#!/usr/bin/env node

import { appendFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const suiteNames = ['dependencies', 'application', 'backend', 'runtime', 'agentcore'];

const sharedVerificationPaths = new Set([
  '.github/workflows/verify.yml',
  'scripts/classify-ci-changes.mjs',
  'scripts/classify-ci-changes.test.mjs',
  'scripts/verify.sh',
]);

const knownNonCodePrefixes = [
  'docs/',
  'output/',
  '.github/ISSUE_TEMPLATE/',
  '.github/PULL_REQUEST_TEMPLATE',
];

const separatelyVerifiedPrefixes = [
  'apps/iOS/',
];

const knownNonCodeFiles = new Set([
  '.gitignore',
  'AGENTS.md',
  'LICENSE',
  'README.md',
]);

function startsWithAny(path, prefixes) {
  return prefixes.some((prefix) => path.startsWith(prefix));
}

function isDependencyDefinition(path) {
  return (
    path === '.github/dependabot.yml'
    || path === 'scripts/audit-dependencies.sh'
    || /(^|\/)(package|package-lock)\.json$/.test(path)
    || /(^|\/)(pyproject\.toml|uv\.lock)$/.test(path)
  );
}

function isKnownNonCode(path) {
  return knownNonCodeFiles.has(path)
    || startsWithAny(path, knownNonCodePrefixes)
    || /(^|\/)(README|LICENSE)(\.[^/]*)?$/.test(path)
    || /\.(md|png|jpe?g|gif|webp)$/.test(path);
}

export function classifyPaths(paths) {
  const normalizedPaths = [...new Set(paths.map((path) => path.trim()).filter(Boolean))];
  const result = Object.fromEntries(suiteNames.map((suite) => [suite, false]));

  for (const path of normalizedPaths) {
    if (sharedVerificationPaths.has(path)) {
      for (const suite of suiteNames) result[suite] = true;
      continue;
    }

    const matched = {
      dependencies: isDependencyDefinition(path),
      application: startsWithAny(path, [
        'apps/website/',
        'catalog/',
        'packages/',
      ]) || path === 'scripts/check-client-entrypoints.mjs'
        || path === 'services/API/amplify/functions/api/api-contract.json'
        || path === 'services/API/scripts/generate-api-contract.mjs',
      backend: path.startsWith('services/API/')
        || path.startsWith('packages/heytim-contract/'),
      runtime: path.startsWith('services/runtime/')
        || path.startsWith('evaluators/')
        || path === 'agentcore/agentcore.json',
      agentcore: path.startsWith('agentcore/')
        || path.startsWith('services/runtime/')
        || path.startsWith('evaluators/'),
    };

    let classified = false;
    for (const suite of suiteNames) {
      if (matched[suite]) {
        result[suite] = true;
        classified = true;
      }
    }

    // New source or automation areas must not silently lose coverage. Documentation,
    // images, and repository metadata are the only changes allowed to skip every suite.
    if (
      !classified
      && !isKnownNonCode(path)
      && !startsWithAny(path, separatelyVerifiedPrefixes)
      && !path.startsWith('.github/workflows/')
    ) {
      for (const suite of suiteNames) result[suite] = true;
    }
  }

  return result;
}

function parseArguments(argumentsToParse) {
  const values = {};
  for (let index = 0; index < argumentsToParse.length; index += 2) {
    const flag = argumentsToParse[index];
    const value = argumentsToParse[index + 1];
    if (!flag?.startsWith('--') || value === undefined) {
      throw new Error('Usage: classify-ci-changes.mjs --base SHA --head SHA --event EVENT --output FILE');
    }
    values[flag.slice(2)] = value;
  }
  return values;
}

function allSuites() {
  return Object.fromEntries(suiteNames.map((suite) => [suite, true]));
}

function resolveChangedPaths({ base, head, event }) {
  if (!base || !head || /^0+$/.test(base)) {
    return { paths: [], forced: true, reason: 'A comparable base commit was unavailable.' };
  }

  try {
    execFileSync('git', ['cat-file', '-e', `${base}^{commit}`], { stdio: 'ignore' });
    execFileSync('git', ['cat-file', '-e', `${head}^{commit}`], { stdio: 'ignore' });
    const separator = event === 'pull_request' ? '...' : '..';
    const output = execFileSync(
      'git',
      ['diff', '--name-only', '--diff-filter=ACDMRTUXB', `${base}${separator}${head}`],
      { encoding: 'utf8' },
    );
    return { paths: output.split('\n').filter(Boolean), forced: false };
  } catch (error) {
    return {
      paths: [],
      forced: true,
      reason: `The changed-file comparison failed: ${error.message}`,
    };
  }
}

function writeOutputs(outputPath, result) {
  const contents = suiteNames.map((suite) => `${suite}=${result[suite]}`).join('\n');
  appendFileSync(outputPath, `${contents}\n`, { encoding: 'utf8' });
}

function main() {
  const { base, head, event, output } = parseArguments(process.argv.slice(2));
  if (!output) throw new Error('--output is required.');

  const changes = resolveChangedPaths({ base, head, event });
  const result = changes.forced ? allSuites() : classifyPaths(changes.paths);
  if (changes.reason) console.warn(`::warning::${changes.reason} Running every verification suite.`);
  console.log(JSON.stringify({ changedPaths: changes.paths, suites: result }, null, 2));
  writeOutputs(output, result);
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}
