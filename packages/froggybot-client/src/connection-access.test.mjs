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

const youtubeConnection = {
  ...gmailConnection,
  id: 'connection_youtube',
  name: 'YouTube Studio',
  provider: 'youtube',
  endpoint: undefined,
};

test('platform-funded tools are included without customer credentials', () => {
  assert.equal(isUserConnection(officialTool), false);
  assert.equal(capabilityAccessLabel(officialTool), 'Included');
});

test('OAuth accounts are connected rather than treated as platform tools', () => {
  assert.equal(isUserConnection(gmailConnection), true);
  assert.equal(capabilityAccessLabel(gmailConnection), 'Connected');
});

test('managed API connections do not need an MCP endpoint', () => {
  assert.equal(isUserConnection(youtubeConnection), true);
  assert.equal(capabilityAccessLabel(youtubeConnection), 'Connected');
});

test('server-side authentication details are not required by clients', () => {
  const { authType: _authType, endpoint: _endpoint, ...publicConnection } = gmailConnection;
  assert.equal(isUserConnection(publicConnection), true);
});

test('catalog tools flow through without a client-side tool allowlist', () => {
  const newlyPublishedTool = {
    id: 'new_catalog_tool',
    name: 'New catalog tool',
    description: 'Published after this app build.',
    provider: 'agentcore-gateway',
    source: 'official',
  };
  const capabilities = [officialTool, gmailConnection, newlyPublishedTool, youtubeConnection];

  assert.deepEqual(
    catalogTools(capabilities).map((tool) => tool.id),
    ['youtube_search', 'new_catalog_tool'],
  );
  assert.deepEqual(
    userConnections(capabilities).map((connection) => connection.id),
    ['connection_gmail', 'connection_youtube'],
  );
});
