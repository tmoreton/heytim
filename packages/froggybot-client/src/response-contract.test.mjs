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

test('accepts arbitrary provider ids and validates server-owned presentation fields', () => {
  const provider = {
    id: 'future-provider',
    name: 'Future Provider',
    description: 'A new server-managed connection.',
    category: 'Productivity',
    iconText: 'FP',
    permissionsSummary: 'Read-only',
    privacyTitle: 'Private by default',
    privacyDescription: 'Access is delegated only when needed.',
    connectLabel: 'Connect workspace',
    reconnectLabel: 'Update workspace',
    familyId: 'future-family',
    familyName: 'Future Family',
    familyIncludedToolIds: ['future-search'],
    serviceName: 'Private access',
  };
  assert.equal(
    decodeBootstrap(bootstrap({ connectionProviders: [provider] })).connectionProviders[0].id,
    'future-provider',
  );
  assert.throws(
    () => decodeBootstrap(bootstrap({ connectionProviders: [{ ...provider, connectLabel: undefined }] })),
    /cannot safely use/,
  );
  assert.throws(
    () => decodeBootstrap(bootstrap({ connectionProviders: [{ ...provider, familyName: 42 }] })),
    /cannot safely use/,
  );
  assert.throws(
    () => decodeBootstrap(bootstrap({ connectionProviders: [{ ...provider, familyIncludedToolIds: [42] }] })),
    /cannot safely use/,
  );
});

test('rejects message actions outside the contract', () => {
  assert.throws(() => decodeMessagePage({
    messages: [{ id: 'message', text: 'hello', status: 'complete', allowedActions: ['deleteEverything'] }],
  }), /cannot safely use/);
});
