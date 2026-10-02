import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const sdk = resolve(fileURLToPath(new URL('.', import.meta.url)),
  'node_modules/bedrock-agentcore/dist/src/tools/browser/live-view/nice-dcv-web-client-sdk');

export default defineConfig({
  base: '/browser-viewer/',
  plugins: [react()],
  resolve: {
    alias: {
      dcv: resolve(sdk, 'dcvjs-esm/dcv.js'),
      'dcv-ui': resolve(sdk, 'dcv-ui/dcv-ui.js'),
    },
    dedupe: ['react', 'react-dom', 'prop-types', '@cloudscape-design/components',
      '@cloudscape-design/global-styles', '@cloudscape-design/design-tokens'],
  },
  build: { target: 'es2022' },
});
