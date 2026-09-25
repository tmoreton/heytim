import { copyFile } from 'node:fs/promises';

const output = new URL('../dist/', import.meta.url);

// GitHub's Pages upload action intentionally omits dot-prefixed paths. Apple
// also supports the association file at the site root, so publish that copy
// from the canonical .well-known source rather than maintaining two files.
await copyFile(
  new URL('.well-known/apple-app-site-association', output),
  new URL('apple-app-site-association', output),
);
