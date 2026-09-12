import assert from 'node:assert/strict';
import test from 'node:test';

import { decodeBootstrap, decodeMessagePage } from './response-contract.ts';

const constraints = Object.fromEntries([
  'botNameMaxLength', 'botTaglineMaxLength', 'botPromptMaxLength', 'groupNameMaxLength',
  'groupMemoryMaxLength', 'messageMaxLength', 'scheduleNameMaxLength', 'schedulePromptMaxLength',
  'scheduleDayOfMonthMin', 'scheduleDayOfMonthMax', 'skillNameMaxLength',
  'skillDescriptionMaxLength', 'skillInstructionsMaxLength', 'memoryMaxLength',
  'maxAttachmentsPerMessage', 'imageMaxBytes', 'documentMaxBytes', 'maxPhotoDimension',
].map((key) => [key, 1]));

const bootstrap = (overrides = {}) => ({
  bots: [{ id: 'bot', name: 'Bot', allowedActions: ['edit'] }],
  botTemplates: [],
  connectionProviders: [],
  needsBotOnboarding: false,
  groups: [{ id: 'group', name: 'Group', allowedActions: ['view'], members: [], bots: [], decisions: [] }],
  tools: [],
  retiredToolIds: [],
  skills: [],
  constraints,
  ...overrides,
});

test('accepts a bootstrap only when server-owned permissions and constraints are present', () => {
  assert.equal(decodeBootstrap(bootstrap()).constraints.messageMaxLength, 1);
  assert.throws(() => decodeBootstrap(bootstrap({ constraints: undefined })), /cannot safely use/);
  assert.throws(() => decodeBootstrap(bootstrap({
    bots: [{ id: 'bot', name: 'Bot', allowedActions: ['becomeAdmin'] }],
  })), /cannot safely use/);
});

test('rejects message actions outside the contract', () => {
  assert.throws(() => decodeMessagePage({
    messages: [{ id: 'message', text: 'hello', status: 'complete', allowedActions: ['deleteEverything'] }],
  }), /cannot safely use/);
});
