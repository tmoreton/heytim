import * as Linking from 'expo-linking';
import { useCallback, useState } from 'react';

import type { FrogBotApi } from '@/lib/api';
import { isPreviewableImage } from '@/lib/file-preview';
import type { Attachment } from '@/lib/types';

export function useFilePreview(
  api: FrogBotApi,
  groupId: string | undefined,
  setError: (message: string) => void,
) {
  const [previewFile, setPreviewFile] = useState<Attachment>();

  const resolveFile = useCallback(
    (fileId: string) => api.downloadFile(fileId, groupId),
    [api, groupId],
  );

  const openFile = useCallback(async (file: Attachment) => {
    if (isPreviewableImage(file)) {
      setPreviewFile(file);
      return;
    }
    try {
      await Linking.openURL(await resolveFile(file.id));
      setError('');
    } catch (value) {
      const error = value instanceof Error ? value : new Error('Could not open that file.');
      setError(error.message);
      throw error;
    }
  }, [resolveFile, setError]);

  return {
    previewFile,
    closePreview: useCallback(() => setPreviewFile(undefined), []),
    openFile,
    resolveFile,
  };
}
