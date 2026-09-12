const path = require('node:path');

const { getDefaultConfig } = require('expo/metro-config');

/** @type {import('expo/metro-config').MetroConfig} */
const config = getDefaultConfig(__dirname);
const workspaceRoot = path.resolve(__dirname, '../..');

// The app consumes source-only workspace packages. Metro must watch those
// files, while resolving their Expo/React peer dependencies from this app.
config.watchFolders = [workspaceRoot];
config.resolver.nodeModulesPaths = [
  path.resolve(__dirname, 'node_modules'),
  path.resolve(workspaceRoot, 'node_modules'),
];

const previewApiPath = path.resolve(
  __dirname,
  process.env.FROGBOT_ENABLE_LOCAL_PREVIEW === '1'
    ? 'src/lib/preview/preview-api.enabled.ts'
    : 'src/lib/preview/preview-api.disabled.ts',
);
const contractsPath = path.resolve(__dirname, '../../packages/froggybot-contract/src/index.ts');
const clientPath = path.resolve(__dirname, '../../packages/froggybot-client/src/index.ts');
const transcriptionPath = path.resolve(__dirname, '../../packages/frogbot-transcription/index.ts');
const previewPath = path.resolve(__dirname, '../../packages/froggybot-preview/src/index.ts');
const expoClientPath = path.resolve(__dirname, '../../packages/froggybot-expo-client/src/index.ts');
const browserHandoffClientPath = path.resolve(__dirname, '../../packages/froggybot-expo-client/src/use-browser-handoff.ts');

config.resolver.resolveRequest = (context, moduleName, platform) => {
  if (moduleName === '@froggybot/preview-api') {
    return { filePath: previewApiPath, type: 'sourceFile' };
  }
  if (moduleName === '@froggybot/contracts') {
    return { filePath: contractsPath, type: 'sourceFile' };
  }
  if (moduleName === '@froggybot/client') {
    return { filePath: clientPath, type: 'sourceFile' };
  }
  if (moduleName === '@froggybot/transcription') {
    return { filePath: transcriptionPath, type: 'sourceFile' };
  }
  if (moduleName === '@froggybot/preview') {
    return { filePath: previewPath, type: 'sourceFile' };
  }
  if (moduleName === '@froggybot/expo-client') {
    return { filePath: expoClientPath, type: 'sourceFile' };
  }
  if (moduleName === '@froggybot/expo-client/use-browser-handoff') {
    return { filePath: browserHandoffClientPath, type: 'sourceFile' };
  }
  return context.resolveRequest(context, moduleName, platform);
};

module.exports = config;
