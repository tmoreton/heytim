import assert from 'node:assert/strict';
import { test } from 'node:test';
import { assertBootstrapReady } from './bootstrap-release-contract.mjs';

const readyBootstrap = () => ({
  bots: [{ id: 'catalog-chief', systemRole: 'chief', templateId: 'chief' }],
  botTemplates: [{ id: 'chief' }, { id: 'trip-planner' }],
});

test('a fresh account with only Chief and an available template is release ready', () => {
  assert.doesNotThrow(() => assertBootstrapReady(readyBootstrap()));
});

test('the installed Chief bot is required', () => {
  assert.throws(
    () => assertBootstrapReady({ ...readyBootstrap(), bots: [] }),
    /installed Chief bot/,
  );
  assert.throws(
    () => assertBootstrapReady({ ...readyBootstrap(), bots: [{ templateId: 'chief' }] }),
    /installed Chief bot/,
  );
});

test('the current Chief catalog template is required', () => {
  assert.throws(
    () => assertBootstrapReady({ ...readyBootstrap(), botTemplates: [{ id: 'trip-planner' }] }),
    /Chief and an installable bot template/,
  );
});

test('a non-Chief template must be available for onboarding', () => {
  assert.throws(
    () => assertBootstrapReady({ ...readyBootstrap(), botTemplates: [{ id: 'chief' }] }),
    /Chief and an installable bot template/,
  );
  assert.throws(() => assertBootstrapReady({ ...readyBootstrap(), botTemplates: null }));
});
