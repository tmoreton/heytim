import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizePathname } from './route.ts';

test('normalizes trailing slashes in linear time without changing the route', () => {
  assert.equal(normalizePathname(''), '/');
  assert.equal(normalizePathname('/'), '/');
  assert.equal(normalizePathname('////'), '/');
  assert.equal(normalizePathname('/library///'), '/library');
  assert.equal(normalizePathname(`/invite${'/'.repeat(100_000)}`), '/invite');
});

