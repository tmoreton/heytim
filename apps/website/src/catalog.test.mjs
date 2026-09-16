import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { availableEntries, filterEntries, invitationAppLink } from './catalog.ts';

const catalog = JSON.parse(readFileSync(new URL('../../../catalog/catalog.json', import.meta.url)));
test('only lists bots and skills whose tools can run', () => {
  const available = availableEntries(catalog);
  assert(available.skills.length > 10);
  assert(available.bots.some((bot) => bot.id === 'chief'));
  const disabled = availableEntries({ ...catalog, tools: [] });
  assert(disabled.skills.every((skill) => skill.requiredToolIds.length === 0));
  assert(!disabled.bots.some((bot) => bot.id === 'chief'));
});
test('searches text and filters categories without mutating the catalog', () => {
  const original = JSON.stringify(catalog);
  assert(filterEntries(catalog.skills, '  thumbnail  ', 'All').some((item) => item.id === 'youtube-thumbnail-director'));
  assert.equal(filterEntries(catalog.skills, 'no-such-skill-12345', 'All').length, 0);
  assert(filterEntries(catalog.skills, '', catalog.skills[0].category).every((item) => item.category === catalog.skills[0].category));
  assert.equal(JSON.stringify(catalog), original);
});
test('preserves invite tokens without accepting arbitrary redirects', () => {
  assert.equal(invitationAppLink('?kind=group&token=abc_123&redirect=https://evil.test'), 'frogbot://invite?kind=group&token=abc_123');
  assert.equal(invitationAppLink('?kind=skill&token=skill-token'), 'frogbot://invite?kind=skill&token=skill-token');
  for (const search of ['', '?redirect=javascript:alert(1)', '?kind=group&kind=bot&token=a', '?kind=group&token=a%0Ab']) {
    assert.equal(invitationAppLink(search), undefined);
  }
});
