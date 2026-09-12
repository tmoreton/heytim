import assert from 'node:assert/strict';
import test from 'node:test';

import {
  capabilityAccessLabel,
  catalogTools,
  isUserConnection,
  userConnections,
} from './connection-access.ts';

const officialTool = {
  id: 'youtube_search',
  name: 'YouTube',
  description: 'Search public videos.',
  provider: 'agentcore-gateway',
};

const gmailConnection = {
  id: 'connection_gmail',
  name: 'Gmail',
  description: 'Search connected email.',
  provider: 'gmail',
  source: 'user',
  editable: true,
  endpoint: 'https://gmailmcp.googleapis.com/mcp/v1',
  authType: 'oauth',
  connectionStatus: 'connected',
};

const legacyConnection = {
  ...gmailConnection,
  id: 'connection_legacy',
  name: 'Private notes',
  provider: 'mcp',
  authType: 'api_key',
};

test('platform-funded tools are included without customer credentials', () => {
  assert.equal(isUserConnection(officialTool), false);
  assert.equal(capabilityAccessLabel(officialTool), 'Included');
});

test('OAuth accounts are connected rather than treated as platform tools', () => {
  assert.equal(isUserConnection(gmailConnection), true);
  assert.equal(capabilityAccessLabel(gmailConnection), 'Connected');
});

test('existing header-auth connections are clearly marked as legacy', () => {
  assert.equal(isUserConnection(legacyConnection), true);
  assert.equal(capabilityAccessLabel(legacyConnection), 'Legacy connection');
});

test('catalog tools flow through without a client-side tool allowlist', () => {
  const newlyPublishedTool = {
    id: 'new_catalog_tool',
    name: 'New catalog tool',
    description: 'Published after this app build.',
    provider: 'agentcore-gateway',
    source: 'official',
  };
  const capabilities = [officialTool, gmailConnection, newlyPublishedTool, legacyConnection];

  assert.deepEqual(
    catalogTools(capabilities).map((tool) => tool.id),
    ['youtube_search', 'new_catalog_tool'],
  );
  assert.deepEqual(
    userConnections(capabilities).map((connection) => connection.id),
    ['connection_gmail', 'connection_legacy'],
  );
});
