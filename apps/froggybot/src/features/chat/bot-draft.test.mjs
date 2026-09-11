import assert from 'node:assert/strict';
import test from 'node:test';

import { createBotDraft } from './bot-draft.ts';

const bot = {
  id: 'research',
  name: 'Research',
  tagline: 'Find useful answers',
  prompt: 'Research carefully.',
  color: '#3984F6',
  toolIds: ['web', 'internal_tool', 'meme_composer', 'retired_tool'],
  extraToolIds: ['web', 'internal_tool', 'meme_composer', 'retired_tool'],
  alwaysAllowedToolIds: ['web', 'internal_tool', 'meme_composer'],
  skillIds: ['planner', 'retired-skill'],
  createdAt: '',
  updatedAt: '',
  lastMessage: '',
  lastMessageAt: '',
};
const tools = [{ id: 'web', name: 'Web', description: 'Read pages', risk: 'interactive' }];
const skills = [{
  id: 'planner',
  version: 1,
  name: 'Planner',
  description: 'Make a plan',
  requiredToolIds: [],
  source: 'official',
  visibility: 'public',
  editable: false,
}];

test('removes explicitly retired tools while preserving supported hidden tools', () => {
  const draft = createBotDraft(bot, skills, tools, ['meme_composer', 'retired_tool'], '#58BEAA');

  assert.deepEqual(draft.toolIds, ['web', 'internal_tool']);
  assert.deepEqual(draft.alwaysAllowedToolIds, ['web', 'internal_tool']);
  assert.deepEqual(draft.skillIds, ['planner']);
});

test('adds only suggestions that still exist in the catalog', () => {
  assert.deepEqual(createBotDraft(undefined, skills, tools, [], '#58BEAA', { kind: 'tool', id: 'web' }).toolIds, ['web']);
  assert.deepEqual(createBotDraft(undefined, skills, tools, [], '#58BEAA', { kind: 'tool', id: 'retired_tool' }).toolIds, []);
});
