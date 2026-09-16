import assert from 'node:assert/strict';
import test from 'node:test';

import { classifyPaths } from './classify-ci-changes.mjs';

test('documentation-only changes skip product verification suites', () => {
  assert.deepEqual(classifyPaths(['README.md', 'docs/operations.md']), {
    dependencies: false,
    application: false,
    backend: false,
    runtime: false,
    agentcore: false,
  });
});

test('Apple-only changes stay out of non-Apple suites', () => {
  assert.deepEqual(classifyPaths(['apps/iOS/Sources/FroggyBotUI/MainView.swift']), {
    dependencies: false,
    application: false,
    backend: false,
    runtime: false,
    agentcore: false,
  });
});

test('website changes run the application suite', () => {
  assert.deepEqual(classifyPaths(['apps/website/src/lib/api.ts']), {
    dependencies: false,
    application: true,
    backend: false,
    runtime: false,
    agentcore: false,
  });
});

test('skill instruction changes verify the catalog and its published website', () => {
  const result = classifyPaths(['catalog/skills/trip-planner/SKILL.md']);
  assert.equal(result.application, true);
  assert.equal(result.backend, false);
  assert.equal(result.runtime, false);
});

test('backend contracts verify both the backend and clients', () => {
  assert.deepEqual(classifyPaths([
    'services/API/amplify/functions/api/api-contract.json',
  ]), {
    dependencies: false,
    application: true,
    backend: true,
    runtime: false,
    agentcore: false,
  });
});

test('runtime changes verify runtime and AgentCore packaging', () => {
  assert.deepEqual(classifyPaths(['services/runtime/runtime/main.py']), {
    dependencies: false,
    application: false,
    backend: false,
    runtime: true,
    agentcore: true,
  });
});

test('dependency definitions add the dependency audit to their owning suite', () => {
  assert.deepEqual(classifyPaths(['services/API/package-lock.json']), {
    dependencies: true,
    application: false,
    backend: true,
    runtime: false,
    agentcore: false,
  });
});

test('unclassified source changes fail open to every suite', () => {
  assert.deepEqual(classifyPaths(['new-service/source.go']), {
    dependencies: true,
    application: true,
    backend: true,
    runtime: true,
    agentcore: true,
  });
});

test('classifier changes verify every suite', () => {
  assert.deepEqual(classifyPaths(['scripts/classify-ci-changes.mjs']), {
    dependencies: true,
    application: true,
    backend: true,
    runtime: true,
    agentcore: true,
  });
});
