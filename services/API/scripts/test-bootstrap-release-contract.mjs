import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { createServer } from 'node:http';
import { test } from 'node:test';
import { promisify } from 'node:util';
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

test('an exhausted synthetic account stops before creating test resources', async () => {
  const requests = [];
  const server = createServer((request, response) => {
    requests.push(`${request.method} ${request.url}`);
    response.setHeader('content-type', 'application/json');
    if (request.url === '/bootstrap') {
      response.end(JSON.stringify(readyBootstrap()));
    } else if (request.url === '/billing') {
      response.end(JSON.stringify({
        creditsUsed: 27, creditsRemaining: 3, creditLimit: 30,
        stripeCustomerId: 'private-billing-marker',
      }));
    } else {
      response.writeHead(400);
      response.end('{}');
    }
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    await assert.rejects(promisify(execFile)(process.execPath, [
      new URL('./authenticated-workflow-test.mjs', import.meta.url).pathname,
    ], {
      env: {
        HEYTIM_API_URL: `http://127.0.0.1:${server.address().port}`,
        HEYTIM_ID_TOKEN: 'local-test-token',
      },
      timeout: 10_000,
    }), (error) => {
      assert.equal(error.code, 1);
      assert.match(error.stderr, /requires at least four remaining credits/);
      assert.doesNotMatch(error.stdout + error.stderr, /private-billing-marker|local-test-token/);
      return true;
    });
    assert.deepEqual(requests, ['GET /bootstrap', 'GET /billing']);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});
