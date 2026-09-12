import assert from 'node:assert/strict';
import test from 'node:test';

import { preparePhotoAttachment } from './photo-attachment.web.ts';

const photo = (overrides = {}) => ({
  uri: 'blob:https://app.froggybot.com/photo',
  width: 1200,
  height: 800,
  type: 'image',
  fileName: 'launch.jpg',
  fileSize: 1_250_000,
  mimeType: 'image/jpeg',
  ...overrides,
});

test('prepares a supported browser photo for upload without changing its bytes', async () => {
  const result = await preparePhotoAttachment(photo(), 1);

  assert.deepEqual(result, {
    uri: 'blob:https://app.froggybot.com/photo',
    name: 'launch.jpg',
    size: 1_250_000,
    mimeType: 'image/jpeg',
    file: undefined,
  });
});

test('rejects unsupported browser photo formats before upload', async () => {
  await assert.rejects(
    preparePhotoAttachment(photo({ fileName: 'launch.heic', mimeType: 'image/heic' }), 1),
    /supported image/,
  );
});

test('rejects oversized browser photos before requesting an upload ticket', async () => {
  await assert.rejects(
    preparePhotoAttachment(photo({ fileSize: 3_750_001 }), 1),
    /too large/,
  );
});
