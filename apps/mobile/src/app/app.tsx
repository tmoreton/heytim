import { useLocalSearchParams } from 'expo-router';

import { AppEntry } from '@/features/app/app-entry';

export default function AppPage() {
  const { preview } = useLocalSearchParams<{ preview?: string | string[] }>();
  const previewValue = Array.isArray(preview) ? preview[0] : preview;
  return <AppEntry preview={__DEV__ && previewValue === '1'} />;
}
