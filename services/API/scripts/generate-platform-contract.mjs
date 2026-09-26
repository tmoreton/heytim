import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const serviceRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repositoryRoot = resolve(serviceRoot, '../..');
const sourcePath = resolve(repositoryRoot, 'packages/heytim-contract/src/platform-contract.json');
const outputs = {
  typescript: resolve(repositoryRoot, 'packages/heytim-contract/src/platform-contract.generated.ts'),
  swift: resolve(repositoryRoot, 'apps/iOS/Sources/HeyTimCore/PlatformContract.generated.swift'),
  apiPython: resolve(serviceRoot, 'amplify/functions/shared/client_contract.py'),
  devicePython: resolve(serviceRoot, 'amplify/functions/shared/device_contract.py'),
  apiProviderPython: resolve(serviceRoot, 'amplify/functions/shared/provider_contract.py'),
  runtimePython: resolve(
    repositoryRoot,
    'services/runtime/runtime/heytim_runtime/device_contract.py',
  ),
  runtimeProviderPython: resolve(
    repositoryRoot,
    'services/runtime/runtime/heytim_runtime/provider_contract.py',
  ),
};
const contract = JSON.parse(readFileSync(sourcePath, 'utf8'));

const fail = (message) => { throw new Error(`Invalid platform contract: ${message}`); };
if (
  contract.version !== 1
  || !contract.constraints
  || !contract.providerRuntimes
  || !contract.deviceCapabilities
) {
  fail('unsupported or incomplete document');
}
for (const [name, value] of Object.entries(contract.constraints)) {
  if (!/^[a-z][A-Za-z0-9]+$/.test(name) || !Number.isSafeInteger(value) || value < 1) {
    fail(`constraint ${name}`);
  }
}
const providerRuntimes = contract.providerRuntimes;
for (const required of ['gmail', 'youtube', 'google_workspace']) {
  if (!providerRuntimes[required]) fail(`missing provider runtime ${required}`);
}
const providerEndpoints = new Set();
for (const [providerId, provider] of Object.entries(providerRuntimes)) {
  if (
    !/^[a-z][a-z0-9_]{0,63}$/.test(providerId)
    || !Array.isArray(provider.oauthScopes)
    || new Set(provider.oauthScopes).size !== provider.oauthScopes.length
    || provider.oauthScopes.some((scope) => typeof scope !== 'string' || !scope || scope.length > 300)
    || !Array.isArray(provider.servers)
  ) {
    fail(`provider runtime ${providerId}`);
  }
  for (const server of provider.servers) {
    let endpoint;
    try { endpoint = new URL(server.endpoint); } catch { fail(`provider endpoint ${server.endpoint}`); }
    if (
      endpoint.protocol !== 'https:'
      || providerEndpoints.has(server.endpoint)
      || !Array.isArray(server.allowedTools)
      || server.allowedTools.length === 0
      || new Set(server.allowedTools).size !== server.allowedTools.length
      || server.allowedTools.some((tool) => !/^[a-z][a-z0-9_]{0,127}$/.test(tool))
      || !server.scopedParameters
      || typeof server.scopedParameters !== 'object'
      || Array.isArray(server.scopedParameters)
      || Object.entries(server.scopedParameters).some(
        ([tool, parameter]) => !server.allowedTools.includes(tool)
          || !/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(parameter),
      )
    ) {
      fail(`provider server ${server.endpoint}`);
    }
    providerEndpoints.add(server.endpoint);
  }
}
const devices = contract.deviceCapabilities;
if (
  devices.version !== 1
  || !Number.isSafeInteger(devices.maxOperationsPerDevice)
  || devices.maxOperationsPerDevice < 1
  || !Array.isArray(devices.tools)
  || devices.tools.length === 0
) {
  fail('device capabilities');
}
const toolIds = new Set();
const operations = new Set();
for (const tool of devices.tools) {
  if (
    !tool
    || typeof tool.id !== 'string'
    || !/^[a-z0-9][a-z0-9_]{0,63}$/.test(tool.id)
    || toolIds.has(tool.id)
    || !['ios', 'macos'].includes(tool.platform)
    || !Array.isArray(tool.operations)
    || tool.operations.length < 1
    || tool.operations.length > devices.maxOperationsPerDevice
    || !Array.isArray(tool.interactiveOperations)
  ) {
    fail(`device tool ${tool?.id ?? '<unknown>'}`);
  }
  toolIds.add(tool.id);
  const localOperations = new Set();
  for (const operation of tool.operations) {
    if (
      typeof operation !== 'string'
      || !/^[a-z][a-z0-9_]{0,127}$/.test(operation)
      || operations.has(operation)
      || localOperations.has(operation)
    ) {
      fail(`device operation ${operation}`);
    }
    operations.add(operation);
    localOperations.add(operation);
  }
  if (
    new Set(tool.interactiveOperations).size !== tool.interactiveOperations.length
    || tool.interactiveOperations.some((operation) => !localOperations.has(operation))
  ) {
    fail(`interactive operations for ${tool.id}`);
  }
}

const snakeUpper = (value) => value.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toUpperCase();
const pyString = (value) => JSON.stringify(value);
const pyList = (values) => `[${values.map(pyString).join(', ')}]`;
const pyTuple = (values) => `(${values.map(pyString).join(', ')}${values.length === 1 ? ',' : ''})`;
const generatedHeader = (source) => `Generated from ${source}. Do not edit directly.`;

const pythonConstraints = [
  `\"\"\"${generatedHeader('packages/heytim-contract/src/platform-contract.json')}\"\"\"`,
  'from __future__ import annotations',
  '',
  ...Object.entries(contract.constraints).map(([name, value]) => `${snakeUpper(name)} = ${value}`),
  '',
  '_CLIENT_CONSTRAINTS = {',
  ...Object.entries(contract.constraints).map(
    ([name]) => `    ${pyString(name)}: ${snakeUpper(name)},`,
  ),
  '}',
  '',
  '',
  'def client_constraints() -> dict:',
  '    return dict(_CLIENT_CONSTRAINTS)',
  '',
].join('\n');

const operationPlatforms = devices.tools.flatMap((tool) =>
  tool.operations.map((operation) => [operation, tool.platform]));
const pythonDevice = [
  `\"\"\"${generatedHeader('packages/heytim-contract/src/platform-contract.json')}\"\"\"`,
  'from __future__ import annotations',
  '',
  `DEVICE_CONTRACT_VERSION = ${devices.version}`,
  `MAX_DEVICE_OPERATIONS = ${devices.maxOperationsPerDevice}`,
  'DEVICE_OPERATION_PLATFORMS = {',
  ...operationPlatforms.map(([operation, platform]) => `    ${pyString(operation)}: ${pyString(platform)},`),
  '}',
  `DEVICE_TOOL_IDS = frozenset(${pyList([...toolIds])})`,
  'DEVICE_TOOL_OPERATIONS = {',
  ...devices.tools.map((tool) => `    ${pyString(tool.id)}: frozenset(${pyList(tool.operations)}),`),
  '}',
  'DEVICE_TOOL_INTERACTIVE_OPERATIONS = {',
  ...devices.tools.map(
    (tool) => `    ${pyString(tool.id)}: frozenset(${pyList(tool.interactiveOperations)}),`,
  ),
  '}',
  '',
].join('\n');

const gmailRuntime = providerRuntimes.gmail;
const youtubeRuntime = providerRuntimes.youtube;
const workspaceRuntime = providerRuntimes.google_workspace;
const gmailServer = gmailRuntime.servers[0];
if (gmailRuntime.servers.length !== 1) fail('Gmail must have exactly one MCP server');
const scopedGoogleTools = workspaceRuntime.servers.filter(
  (server) => Object.keys(server.scopedParameters).length > 0,
);
const pythonProvider = [
  `\"\"\"${generatedHeader('packages/heytim-contract/src/platform-contract.json')}\"\"\"`,
  'from __future__ import annotations',
  '',
  `GMAIL_MCP_ENDPOINT = ${pyString(gmailServer.endpoint)}`,
  `GMAIL_MCP_TOOLS = frozenset(${pyList(gmailServer.allowedTools)})`,
  `GMAIL_OAUTH_SCOPES = ${pyTuple(gmailRuntime.oauthScopes)}`,
  `YOUTUBE_OAUTH_SCOPES = ${pyTuple(youtubeRuntime.oauthScopes)}`,
  `GOOGLE_WORKSPACE_OAUTH_SCOPES = ${pyTuple(workspaceRuntime.oauthScopes)}`,
  'GOOGLE_WORKSPACE_SCOPES = frozenset(GOOGLE_WORKSPACE_OAUTH_SCOPES)',
  'GOOGLE_WORKSPACE_MCP_SERVERS = {',
  ...workspaceRuntime.servers.map(
    (server) => `    ${pyString(server.endpoint)}: frozenset(${pyList(server.allowedTools)}),`,
  ),
  '}',
  'SCOPED_GOOGLE_TOOLS = {',
  ...scopedGoogleTools.map((server) => [
    `    ${pyString(new URL(server.endpoint).hostname)}: {`,
    ...Object.entries(server.scopedParameters).map(
      ([tool, parameter]) => `        ${pyString(tool)}: ${pyString(parameter)},`,
    ),
    '    },',
  ].join('\n')),
  '}',
  '',
].join('\n');

const typescript = [
  `// ${generatedHeader('platform-contract.json')}`,
  `export const platformContractVersion = ${contract.version} as const;`,
  `export const appConstraints = ${JSON.stringify(contract.constraints, null, 2)} as const;`,
  `export const providerRuntimeContract = ${JSON.stringify(providerRuntimes, null, 2)} as const;`,
  `export const deviceCapabilityContract = ${JSON.stringify(devices, null, 2)} as const;`,
  '',
].join('\n');

const swiftString = (value) => JSON.stringify(value).replaceAll('\\/', '/');
const swift = [
  `// ${generatedHeader('packages/heytim-contract/src/platform-contract.json')}`,
  'import Foundation',
  '',
  'public enum GeneratedAppConstraints {',
  ...Object.entries(contract.constraints).map(
    ([name, value]) => `  public static let ${name} = ${value}`,
  ),
  '}',
  '',
  'public enum GeneratedDeviceCapabilities {',
  `  public static let version = ${devices.version}`,
  `  public static let maxOperationsPerDevice = ${devices.maxOperationsPerDevice}`,
  '  public static let operationsByTool: [String: [String]] = [',
  ...devices.tools.map(
    (tool) => `    ${swiftString(tool.id)}: [${tool.operations.map(swiftString).join(', ')}],`,
  ),
  '  ]',
  '  public static let interactiveOperationsByTool: [String: [String]] = [',
  ...devices.tools.map(
    (tool) => `    ${swiftString(tool.id)}: [${tool.interactiveOperations.map(swiftString).join(', ')}],`,
  ),
  '  ]',
  '}',
  '',
].join('\n');

const rendered = new Map([
  [outputs.typescript, typescript],
  [outputs.swift, swift],
  [outputs.apiPython, pythonConstraints],
  [outputs.devicePython, pythonDevice],
  [outputs.runtimePython, pythonDevice],
  [outputs.apiProviderPython, pythonProvider],
  [outputs.runtimeProviderPython, pythonProvider],
]);
if (process.argv.includes('--check')) {
  for (const [path, expected] of rendered) {
    if (!existsSync(path) || readFileSync(path, 'utf8') !== expected) {
      throw new Error(`Platform contract output is stale: ${path}`);
    }
  }
} else {
  for (const [path, content] of rendered) writeFileSync(path, content);
}
