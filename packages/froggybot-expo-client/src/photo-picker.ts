import * as ImagePicker from 'expo-image-picker';
import type { ImagePickerAsset } from 'expo-image-picker';

export async function selectPhotos(limit: number): Promise<ImagePickerAsset[] | null> {
  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ['images'],
    allowsMultipleSelection: true,
    orderedSelection: true,
    selectionLimit: limit,
    shouldDownloadFromNetwork: true,
    quality: 1,
  });
  return result.canceled ? null : result.assets.slice(0, limit);
}
