import type { ImagePickerAsset } from 'expo-image-picker';

import type { AppConstraints, UploadAsset } from '@froggybot/contracts';

const WEB_PHOTO_TYPES: Record<string, string> = {
  '.gif': 'image/gif',
  '.jpeg': 'image/jpeg',
  '.jpg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
};

export async function preparePhotoAttachment(
  asset: ImagePickerAsset,
  position: number,
  constraints: Pick<AppConstraints, 'imageMaxBytes' | 'maxPhotoDimension'>,
): Promise<UploadAsset> {
  const name = asset.fileName?.trim() || `Photo ${position}`;
  const extension = name.toLowerCase().match(/\.[a-z0-9]+$/)?.[0];
  const expectedType = extension ? WEB_PHOTO_TYPES[extension] : undefined;
  const size = asset.fileSize ?? asset.file?.size ?? 0;
  if (!expectedType || (asset.mimeType && asset.mimeType !== expectedType)) {
    throw new Error(`${name} is not a supported image. Choose a JPEG, PNG, GIF, or WebP file.`);
  }
  if (size < 1) throw new Error(`Could not read the size of ${name}.`);
  if (size > constraints.imageMaxBytes) throw new Error(`${name} is too large to attach.`);
  return {
    uri: asset.uri,
    name,
    size,
    mimeType: expectedType,
    file: asset.file,
  };
}
