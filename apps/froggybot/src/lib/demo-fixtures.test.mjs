import assert from 'node:assert/strict';
import test from 'node:test';

import { createInitialDemoBots, toolIdsForTemplate } from './demo-fixtures.ts';

const template = {
  id: 'trip-planner',
  version: 8,
  name: 'Catalog Trip Planner',
  tagline: 'Fresh catalog copy',
  prompt: 'Use the current catalog instructions.',
  color: '#3984F6',
  skillIds: ['trip-planner'],
  toolIds: ['web_search'],
};

const skills = [{
  id: 'trip-planner',
  version: 3,
  name: 'Trip planner',
  description: 'Plan a trip.',
  requiredToolIds: ['new_catalog_tool'],
  source: 'official',
  visibility: 'public',
  editable: false,
}];

test('demo bots inherit current catalog metadata and tool requirements', () => {
  const [bot] = createInitialDemoBots([template], skills, '2026-09-12T00:00:00Z');

  assert.equal(bot.name, 'Catalog Trip Planner');
  assert.equal(bot.prompt, 'Use the current catalog instructions.');
  assert.equal(bot.templateVersion, 8);
  assert.deepEqual(bot.toolIds, ['web_search', 'new_catalog_tool']);
});

test('new catalog requirements need no client-side tool registration', () => {
  const updatedSkills = [{ ...skills[0], requiredToolIds: ['future_tool'] }];

  assert.deepEqual(toolIdsForTemplate(template, updatedSkills), ['web_search', 'future_tool']);
});
