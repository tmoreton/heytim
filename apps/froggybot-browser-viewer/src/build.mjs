import { build } from 'esbuild';
import { cp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { privateLiveViewSource } from './sdk-compatibility.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const app = resolve(here, '..');
const sdk = resolve(app, 'node_modules/bedrock-agentcore/dist/src/tools/browser/live-view');
const output = resolve(app, 'dist/bot-browser');
await mkdir(output, { recursive: true });
// Decoder workers and their imports need stable same-origin paths on web and in
// native WebView. Preserve AWS's license notices with the unmodified SDK assets.
await cp(resolve(sdk, 'nice-dcv-web-client-sdk/dcvjs-esm'), resolve(app, 'dist/nice-dcv-web-client-sdk/dcvjs-esm'), { recursive: true });
await cp(resolve(sdk, 'nice-dcv-web-client-sdk/dcv-ui/EULA.txt'), resolve(output, 'DCV-UI-EULA.txt'));
await cp(resolve(sdk, 'nice-dcv-web-client-sdk/dcv-ui/third-party-licenses.txt'), resolve(output, 'third-party-licenses.txt'));
await build({
  absWorkingDir: app,
  entryPoints: [resolve(here, 'entry.tsx')],
  outfile: resolve(output, 'viewer.js'),
  bundle: true,
  format: 'iife',
  platform: 'browser',
  target: ['safari16.4', 'chrome110'],
  jsx: 'automatic',
  minify: true,
  sourcemap: false,
  legalComments: 'linked',
  define: { 'process.env.NODE_ENV': '"production"' },
  alias: {
    dcv: resolve(sdk, 'nice-dcv-web-client-sdk/dcvjs-esm/dcv.js'),
    'dcv-ui': resolve(sdk, 'nice-dcv-web-client-sdk/dcv-ui/dcv-ui.js'),
  },
  plugins: [{
    name: 'private-live-view-diagnostics',
    setup(builder) {
      builder.onLoad({ filter: /BrowserLiveView\.js$/ }, async ({ path }) => {
        return { contents: privateLiveViewSource(await readFile(path, 'utf8')), loader: 'js' };
      });
    },
  }],
});
await writeFile(resolve(output, 'index.html'), `<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><title>FroggyBot private browser</title><link rel="stylesheet" href="./viewer.css">
<style>html,body,#root{width:100%;height:100%;margin:0;overflow:hidden}body{font:14px system-ui;background:#e9eeea}p{padding:16px}</style>
</head><body><div id="notice" role="status" style="position:absolute;z-index:9999;top:0;left:0;right:0;background:#fff2cf;font:12px system-ui"></div><div id="root"></div><script src="./viewer.js" defer></script></body></html>`);
console.log('Built isolated bot browser viewer and AWS decoder assets.');
