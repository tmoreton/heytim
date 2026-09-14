import assert from 'node:assert/strict';
import test from 'node:test';

import {
  capabilityAccessLabel,
  catalogTools,
  connectionProviderFamilies,
  connectionProviderToolGroups,
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

test('tool families combine included and connected capabilities without merging ids', () => {
  const providers = [
    {
      id: 'x',
      name: 'X',
      description: 'Account access.',
      iconText: 'X',
      familyId: 'x',
      familyName: 'X',
      familyDescription: 'Public and private X tools.',
      familyIconText: 'X',
      familyIncludedToolIds: ['x_search'],
      serviceName: 'Account access',
    },
  ];
  const connectedX = {
    ...gmailConnection,
    id: 'connection_x',
    name: 'X',
    provider: 'x',
  };
  const publicX = {
    id: 'x_search',
    name: 'X / Twitter search',
    description: 'Search public posts.',
    provider: 'agentcore-gateway',
  };

  const grouped = connectionProviderToolGroups([officialTool, publicX, connectedX], providers);

  assert.deepEqual(grouped.groups[0].tools.map((tool) => tool.id), ['x_search', 'connection_x']);
  assert.deepEqual(grouped.ungrouped.map((tool) => tool.id), ['youtube_search']);
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

test('provider families group related services without merging their grants', () => {
  const sharedFamily = {
    familyId: 'google',
    familyName: 'Google',
    familyDescription: 'Connect only the services each bot needs.',
    familyIconText: 'G',
    familyLogoProviderId: 'google_workspace',
    familyIncludedSummary: 'Public YouTube research included',
    familyIncludedToolIds: ['youtube_search'],
  };
  const providers = [
    {
      id: 'github', name: 'GitHub', description: 'Repositories.', iconText: 'GH',
    },
    {
      id: 'gmail', name: 'Gmail', description: 'Email.', iconText: 'G',
      serviceName: 'Gmail', ...sharedFamily,
    },
    {
      id: 'youtube', name: 'YouTube Studio', description: 'Channel.', iconText: 'YT',
      serviceName: 'YouTube Studio', ...sharedFamily,
    },
  ];

  const families = connectionProviderFamilies(providers);

  assert.equal(families.length, 2);
  assert.equal(families[0].grouped, false);
  assert.equal(families[1].name, 'Google');
  assert.equal(families[1].includedSummary, 'Public YouTube research included');
  assert.deepEqual(families[1].includedToolIds, ['youtube_search']);
  assert.deepEqual(families[1].providers.map((provider) => provider.id), ['gmail', 'youtube']);
});
