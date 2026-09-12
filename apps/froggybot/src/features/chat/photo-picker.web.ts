import * as DocumentPicker from 'expo-document-picker';
import type { ImagePickerAsset } from 'expo-image-picker';

const WEB_IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp'];

export async function selectPhotos(limit: number): Promise<ImagePickerAsset[] | null> {
  const result = await DocumentPicker.getDocumentAsync({
    type: WEB_IMAGE_TYPES,
    multiple: true,
  });
  if (result.canceled) return null;
  return result.assets.slice(0, limit).map((asset) => ({
    uri: asset.uri,
    width: 0,
    height: 0,
    type: 'image',
    fileName: asset.name,
    fileSize: asset.size,
    mimeType: asset.mimeType,
    file: asset.file,
  }));
}
