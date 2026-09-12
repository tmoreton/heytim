// Ephemeral localhost fixture, no real API calls or browser session credentials.
import { build } from 'esbuild';
import { createServer } from 'node:http';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const app = resolve(here, '..');
const expoApp = resolve(here, '../../froggybot');
const bundle = await build({ entryPoints: [resolve(here, 'ui-fixture.tsx')], bundle: true, write: false,
  absWorkingDir: app, platform: 'browser', format: 'iife', jsx: 'automatic',
  define: { 'process.env.NODE_ENV': '"production"', __DEV__: 'false' },
  alias: { '@': resolve(expoApp, 'src'), '@froggybot/client': resolve(app, '../../packages/froggybot-client/src/index.ts'),
    'react': resolve(app, 'node_modules/react'), 'react-native': 'react-native-web', 'react-native-safe-area-context': resolve(app, 'node_modules/react-native-safe-area-context/src/index.tsx'),
    'expo-clipboard': resolve(here, 'fixture-device-api.ts'), 'expo-linking': resolve(here, 'fixture-device-api.ts') },
  resolveExtensions: ['.web.tsx', '.web.ts', '.web.js', '.tsx', '.ts', '.js'],
});
createServer((request, response) => {
  response.setHeader('cache-control', 'no-store');
  if (request.url === '/fixture.js') { response.setHeader('content-type', 'text/javascript'); response.end(bundle.outputFiles[0].contents); }
  else if (request.url === '/bot-browser/index.html') { response.setHeader('content-type', 'text/html'); response.end('<!doctype html><html><body>Test remote viewer placeholder — no network connection.</body></html>'); }
  else { response.setHeader('content-type', 'text/html'); response.end('<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>html,body,#root{height:100%;margin:0}</style></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>'); }
}).listen(8917, '127.0.0.1', () => console.log('Frontend fixture ready at http://127.0.0.1:8917 (mock API only).'));
