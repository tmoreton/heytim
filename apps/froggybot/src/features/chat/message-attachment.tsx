import { useEffect, useState } from 'react';
import { ActivityIndicator, Image, Pressable, StyleSheet, Text, View } from 'react-native';

import { isPreviewableImage, readableFileSize } from '@froggybot/client';
import type { Attachment } from '@froggybot/contracts';

type Props = {
  file: Attachment;
  assistant: boolean;
  onOpenFile: (file: Attachment) => Promise<void>;
  onResolveFile: (fileId: string) => Promise<string>;
};

export function MessageAttachment({ file, assistant, onOpenFile, onResolveFile }: Props) {
  const image = isPreviewableImage(file);
  const [retry, setRetry] = useState(0);
  const requestKey = `${file.id}:${retry}`;
  const [preview, setPreview] = useState<{ key: string; url?: string; error?: string }>();
  const [opening, setOpening] = useState(false);
  const [opened, setOpened] = useState(false);
  const currentPreview = preview?.key === requestKey ? preview : undefined;
  const imageUrl = currentPreview?.url ?? '';
  const imageError = currentPreview?.error ?? '';

  useEffect(() => {
    if (!image) return;
    let active = true;
    onResolveFile(file.id)
      .then((url) => {
        if (active) setPreview({ key: requestKey, url });
      })
      .catch(() => {
        if (active) setPreview({ key: requestKey, error: 'Could not load this preview.' });
      });
    return () => {
      active = false;
    };
  }, [file.id, image, onResolveFile, requestKey]);

  if (image) {
    const details = (
      <View style={styles.imageDetails}>
        <View style={styles.fileCopy}>
          <Text numberOfLines={1} style={[styles.fileName, !assistant && styles.userText]}>{file.name}</Text>
          <Text style={[styles.fileMeta, !assistant && styles.userMeta]}>
            {readableFileSize(file.size)} · {imageUrl ? 'Tap to expand' : 'Image'}
          </Text>
        </View>
        {imageUrl ? <Text style={[styles.expandIcon, !assistant && styles.userText]}>↗</Text> : null}
      </View>
    );
    return (
      <View
        testID={`image-attachment-${file.id}`}
        style={[styles.imageCard, assistant ? styles.assistantFile : styles.userFile]}>
        {imageUrl ? (
          <Pressable
            accessibilityLabel={`Preview ${file.name}`}
            accessibilityRole="button"
            style={({ pressed }) => [styles.imageButton, pressed && styles.pressed]}
            onPress={() => void onOpenFile(file)}>
            <View style={styles.imageFrame}>
              <Image
                accessibilityLabel={file.name}
                accessibilityRole="image"
                resizeMode="contain"
                source={{ uri: imageUrl }}
                style={styles.image}
                onError={() => {
                  setPreview({ key: requestKey, error: 'Could not load this preview.' });
                }}
              />
            </View>
            {details}
          </Pressable>
        ) : (
          <>
            <View style={styles.imageFrame}>
              {imageError ? (
                <View style={styles.imageStatus}>
                  <Text style={styles.imageError}>{imageError}</Text>
                  <Pressable
                    accessibilityLabel={`Retry preview ${file.name}`}
                    accessibilityRole="button"
                    style={({ pressed }) => [styles.retryButton, pressed && styles.pressed]}
                    onPress={() => setRetry((value) => value + 1)}>
                    <Text style={styles.retryText}>Try again</Text>
                  </Pressable>
                </View>
              ) : (
                <View accessibilityLabel={`Loading preview ${file.name}`} accessibilityRole="progressbar" style={styles.imageStatus}>
                  <ActivityIndicator color="#007A3D" />
                  <Text style={styles.loadingText}>Loading preview…</Text>
                </View>
              )}
            </View>
            {details}
          </>
        )}
      </View>
    );
  }

  const action = opening ? 'Opening…' : opened ? 'Opened' : 'Open file';
  return (
    <Pressable
      accessibilityLabel={`${action} ${file.name}`}
      accessibilityRole="button"
      accessibilityState={{ busy: opening, disabled: opening }}
      disabled={opening}
      style={({ pressed }) => [
        styles.fileChip,
        assistant ? styles.assistantFile : styles.userFile,
        pressed && styles.pressed,
      ]}
      onPress={() => {
        setOpening(true);
        void onOpenFile(file)
          .then(() => setOpened(true))
          .catch(() => undefined)
          .finally(() => setOpening(false));
      }}>
      <Text style={[styles.fileIcon, !assistant && styles.userText]}>↗</Text>
      <View style={styles.fileCopy}>
        <Text numberOfLines={1} style={[styles.fileName, !assistant && styles.userText]}>{file.name}</Text>
        <Text style={[styles.fileMeta, !assistant && styles.userMeta]}>{readableFileSize(file.size)} · {action}</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  assistantFile: { backgroundColor: '#E1E2DE' },
  userFile: { backgroundColor: 'rgba(255,255,255,0.16)' },
  imageCard: { width: '100%', maxWidth: 560, borderRadius: 13, overflow: 'hidden', marginBottom: 10 },
  imageButton: { width: '100%' },
  imageFrame: { width: '100%', aspectRatio: 16 / 9, maxHeight: 315, backgroundColor: '#D8DAD5', alignItems: 'center', justifyContent: 'center' },
  image: { width: '100%', height: '100%' },
  imageStatus: { alignItems: 'center', justifyContent: 'center', gap: 8 },
  imageError: { color: '#7C342B', fontSize: 12, fontWeight: '600' },
  retryButton: { minHeight: 36, justifyContent: 'center', paddingHorizontal: 12 },
  retryText: { color: '#007A3D', fontSize: 12, fontWeight: '800' },
  loadingText: { color: '#5F665F', fontSize: 11 },
  imageDetails: { minHeight: 50, flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 11, paddingVertical: 7 },
  expandIcon: { color: '#007A3D', fontSize: 20, fontWeight: '700' },
  fileChip: { minWidth: 190, maxWidth: 280, flexDirection: 'row', alignItems: 'center', gap: 8, borderRadius: 11, padding: 8, marginBottom: 8 },
  fileIcon: { color: '#007A3D', fontSize: 20, fontWeight: '700' },
  fileCopy: { flex: 1, minWidth: 0 },
  fileName: { color: '#292823', fontSize: 12, fontWeight: '700' },
  fileMeta: { color: '#77736B', fontSize: 10, marginTop: 1 },
  userText: { color: 'white' },
  userMeta: { color: 'rgba(255,255,255,0.72)' },
  pressed: { opacity: 0.68 },
});
