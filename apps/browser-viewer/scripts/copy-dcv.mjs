import { cp } from 'node:fs/promises';

const source = new URL('../node_modules/bedrock-agentcore/dist/src/tools/browser/live-view/nice-dcv-web-client-sdk/dcvjs-esm/', import.meta.url);
const output = new URL('../dist/nice-dcv-web-client-sdk/dcvjs-esm/', import.meta.url);

await cp(source, output, { recursive: true });
