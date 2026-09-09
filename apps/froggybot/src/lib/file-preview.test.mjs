import assert from 'node:assert/strict';
import test from 'node:test';

import { isPreviewableImage, readableFileSize } from './file-preview.ts';

const file = (overrides = {}) => ({
  id: 'file-1', name: 'preview.png', size: 42_000, kind: 'image',
  format: 'png', contentType: 'image/png', ...overrides,
});

test('only known image formats are rendered inside the app', () => {
  assert.equal(isPreviewableImage(file()), true);
  assert.equal(isPreviewableImage(file({ contentType: 'IMAGE/JPEG' })), true);
  assert.equal(isPreviewableImage(file({ kind: 'document', contentType: 'image/png' })), false);
  assert.equal(isPreviewableImage(file({ contentType: 'image/svg+xml' })), false);
  assert.equal(isPreviewableImage(file({ contentType: 'text/html' })), false);
});

test('file sizes are readable without implying false precision', () => {
  assert.equal(readableFileSize(42_000), '42 KB');
  assert.equal(readableFileSize(1_250_000), '1.3 MB');
  assert.equal(readableFileSize(12_500_000), '13 MB');
});
