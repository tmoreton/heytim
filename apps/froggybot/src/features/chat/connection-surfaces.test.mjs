import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('customer connection screens do not expose developer-key entry controls', async () => {
  const sources = await Promise.all([
    readFile(new URL('./connections.tsx', import.meta.url), 'utf8'),
    readFile(new URL('./skill-library.tsx', import.meta.url), 'utf8'),
  ]);
  const customerSurface = sources.join('\n');
  assert.doesNotMatch(customerSurface, /Add tool|Bearer token|API key header|Paste credential/);
  assert.doesNotMatch(sources[0], /provider\s*===\s*['"]gmail|Gmail/);
  assert.match(sources[0], /providers\.map/);
});
