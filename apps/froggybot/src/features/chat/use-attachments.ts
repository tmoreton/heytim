import { useCallback, useRef, useState } from 'react';
import * as DocumentPicker from 'expo-document-picker';

import type { FrogBotApi } from '@/lib/api';
import type { Attachment } from '@/lib/types';

const MAX_ATTACHMENTS = 5;
const ATTACHMENT_TYPES = [
  'application/pdf',
  'text/csv',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'text/html',
  'text/plain',
  'text/markdown',
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
];

type Options = {
  api: FrogBotApi;
  disabled: boolean;
  setError: (message: string) => void;
};

export function useAttachments({ api, disabled, setError }: Options) {
  const request = useRef(0);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);

  const clear = useCallback(() => {
    request.current += 1;
    setAttachments([]);
    setUploading(false);
  }, []);

  const remove = useCallback((fileId: string) => {
    setAttachments((current) => current.filter((item) => item.id !== fileId));
  }, []);

  const pick = useCallback(async () => {
    if (disabled || uploading) return;
    const requestId = ++request.current;
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: ATTACHMENT_TYPES,
        multiple: true,
        copyToCacheDirectory: true,
      });
      if (result.canceled || requestId !== request.current) return;
      const selected = result.assets.slice(0, MAX_ATTACHMENTS - attachments.length);
      if (selected.length === 0) {
        setError(`Attach up to ${MAX_ATTACHMENTS} files per message.`);
        return;
      }
      setUploading(true);
      for (const asset of selected) {
        if (!asset.size) throw new Error(`Could not read the size of ${asset.name}.`);
        const uploaded = await api.uploadAttachment({
          uri: asset.uri,
          name: asset.name,
          size: asset.size,
          mimeType: asset.mimeType,
          file: asset.file,
        });
        if (requestId !== request.current) return;
        setAttachments((current) => [...current, uploaded].slice(0, MAX_ATTACHMENTS));
      }
      setError('');
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not attach that file.');
    } finally {
      if (requestId === request.current) setUploading(false);
    }
  }, [api, attachments.length, disabled, setError, uploading]);

  return { attachments, uploading, clear, pick, remove, setAttachments };
}
