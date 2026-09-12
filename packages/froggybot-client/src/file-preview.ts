import type { Attachment } from '@froggybot/contracts';

const previewableImageTypes = new Set([
  'image/gif',
  'image/jpeg',
  'image/png',
  'image/webp',
]);

export const isPreviewableImage = (file: Attachment) =>
  file.kind === 'image' && previewableImageTypes.has(file.contentType.toLowerCase());

export const readableFileSize = (bytes: number) =>
  bytes >= 1_000_000
    ? `${(bytes / 1_000_000).toFixed(bytes >= 10_000_000 ? 0 : 1)} MB`
    : `${Math.max(1, Math.round(bytes / 1_000))} KB`;
