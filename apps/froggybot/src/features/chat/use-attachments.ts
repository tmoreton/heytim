import { useCallback, useRef, useState } from 'react';
import * as DocumentPicker from 'expo-document-picker';

import type { FrogBotApi, UploadAsset } from '@/lib/api';
import type { Attachment } from '@/lib/types';

import { preparePhotoAttachment } from './photo-attachment';
import { selectPhotos } from './photo-picker';

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
  const [pickerOpen, setPickerOpen] = useState(false);
  const [uploading, setUploading] = useState(false);

  const clear = useCallback(() => {
    request.current += 1;
    setAttachments([]);
    setPickerOpen(false);
    setUploading(false);
  }, []);

  const remove = useCallback((fileId: string) => {
    setAttachments((current) => current.filter((item) => item.id !== fileId));
  }, []);

  const uploadSelection = useCallback(async <T>(
    requestId: number,
    selected: T[],
    prepare: (asset: T, position: number) => Promise<UploadAsset>,
  ) => {
    if (selected.length === 0) {
      setError(`Attach up to ${MAX_ATTACHMENTS} files per message.`);
      return;
    }
    setUploading(true);
    try {
      for (const [index, asset] of selected.entries()) {
        const pending = await prepare(asset, attachments.length + index + 1);
        if (requestId !== request.current) return;
        const uploaded = await api.uploadAttachment(pending);
        if (requestId !== request.current) return;
        setAttachments((current) => [...current, uploaded].slice(0, MAX_ATTACHMENTS));
      }
      setError('');
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not attach that file.');
    } finally {
      if (requestId === request.current) setUploading(false);
    }
  }, [api, attachments.length, setError]);

  const openPicker = useCallback(() => {
    if (disabled || uploading) return;
    if (attachments.length >= MAX_ATTACHMENTS) {
      setError(`Attach up to ${MAX_ATTACHMENTS} files per message.`);
      return;
    }
    setPickerOpen(true);
  }, [attachments.length, disabled, setError, uploading]);

  const closePicker = useCallback(() => setPickerOpen(false), []);

  const pickFiles = useCallback(async () => {
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
      await uploadSelection(requestId, selected, async (asset) => {
        if (!asset.size) throw new Error(`Could not read the size of ${asset.name}.`);
        return {
          uri: asset.uri,
          name: asset.name,
          size: asset.size,
          mimeType: asset.mimeType,
          file: asset.file,
        };
      });
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not attach that file.');
    }
  }, [attachments.length, disabled, setError, uploadSelection, uploading]);

  const pickPhotos = useCallback(async () => {
    if (disabled || uploading) return;
    const requestId = ++request.current;
    try {
      const selected = await selectPhotos(MAX_ATTACHMENTS - attachments.length);
      if (!selected || requestId !== request.current) return;
      await uploadSelection(requestId, selected, preparePhotoAttachment);
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not attach that photo.');
    }
  }, [attachments.length, disabled, setError, uploadSelection, uploading]);

  return {
    attachments,
    uploading,
    pickerOpen,
    clear,
    closePicker,
    openPicker,
    pickFiles,
    pickPhotos,
    remove,
  };
}
