import { File as ExpoFile } from 'expo-file-system';
import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';
import type { ImagePickerAsset } from 'expo-image-picker';

import type { UploadAsset } from '@/lib/api';

const MAX_IMAGE_BYTES = 3_750_000;
const MAX_PHOTO_DIMENSION = 1_920;
const JPEG_QUALITY_ATTEMPTS = [0.82, 0.64, 0.48] as const;
const PHOTO_CONTENT_TYPES: Record<string, string> = {
  '.gif': 'image/gif',
  '.jpeg': 'image/jpeg',
  '.jpg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
};

const extensionOf = (name: string) => name.toLowerCase().match(/\.[a-z0-9]+$/)?.[0];

const readableSize = (asset: ImagePickerAsset) =>
  asset.fileSize ?? new ExpoFile(asset.uri).size;

const normalizedName = (asset: ImagePickerAsset, position: number) => {
  const original = asset.fileName?.trim();
  const base = original?.replace(/\.[^.]+$/, '').trim();
  return `${base || `Photo ${position}`}.jpg`;
};

export async function preparePhotoAttachment(
  asset: ImagePickerAsset,
  position: number,
): Promise<UploadAsset> {
  const originalName = asset.fileName?.trim() || `Photo ${position}`;
  const extension = extensionOf(originalName);
  const expectedType = extension ? PHOTO_CONTENT_TYPES[extension] : undefined;
  const originalSize = readableSize(asset);
  const hasMatchingType = !asset.mimeType || asset.mimeType === expectedType;
  if (
    expectedType
    && hasMatchingType
    && originalSize > 0
    && originalSize <= MAX_IMAGE_BYTES
  ) {
    return {
      uri: asset.uri,
      name: originalName,
      size: originalSize,
      mimeType: expectedType,
      file: asset.file,
    };
  }

  const context = ImageManipulator.manipulate(asset.uri);
  const largestDimension = Math.max(asset.width, asset.height);
  if (largestDimension > MAX_PHOTO_DIMENSION) {
    if (asset.width >= asset.height) context.resize({ width: MAX_PHOTO_DIMENSION });
    else context.resize({ height: MAX_PHOTO_DIMENSION });
  }
  const rendered = await context.renderAsync();
  const name = normalizedName(asset, position);
  for (const compress of JPEG_QUALITY_ATTEMPTS) {
    const result = await rendered.saveAsync({ compress, format: SaveFormat.JPEG });
    const size = new ExpoFile(result.uri).size;
    if (size > 0 && size <= MAX_IMAGE_BYTES) {
      return {
        uri: result.uri,
        name,
        size,
        mimeType: 'image/jpeg',
      };
    }
  }
  throw new Error(`${originalName} is too large to attach.`);
}
