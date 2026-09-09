import * as Linking from 'expo-linking';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Image, Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useModalFocus } from '@/components/use-modal-focus';
import { readableFileSize } from '@/lib/file-preview';
import type { Attachment } from '@/lib/types';

type Props = {
  file: Attachment;
  onClose: () => void;
  onResolveFile: (fileId: string) => Promise<string>;
};

export function ImagePreviewModal({ file, onClose, onResolveFile }: Props) {
  const insets = useSafeAreaInsets();
  const modalRef = useModalFocus(onClose);
  const [retry, setRetry] = useState(0);
  const requestKey = `${file.id}:${retry}`;
  const [preview, setPreview] = useState<{ key: string; url?: string; error?: string }>();
  const [opening, setOpening] = useState(false);
  const currentPreview = preview?.key === requestKey ? preview : undefined;
  const url = currentPreview?.url ?? '';
  const error = currentPreview?.error ?? '';

  useEffect(() => {
    let active = true;
    onResolveFile(file.id)
      .then((value) => {
        if (active) setPreview({ key: requestKey, url: value });
      })
      .catch(() => {
        if (active) setPreview({ key: requestKey, error: 'Could not load this image.' });
      });
    return () => {
      active = false;
    };
  }, [file.id, onResolveFile, requestKey]);

  const openOriginal = async () => {
    setOpening(true);
    try {
      await Linking.openURL(url || await onResolveFile(file.id));
    } catch {
      setPreview({ key: requestKey, error: 'Could not open the original image.' });
    } finally {
      setOpening(false);
    }
  };

  return (
    <Modal animationType="fade" transparent visible onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View
          ref={modalRef}
          accessibilityLabel={`Image preview: ${file.name}`}
          accessibilityViewIsModal
          style={[
            styles.modal,
            { marginTop: 12 + insets.top, marginBottom: 12 + insets.bottom },
          ]}>
          <View style={styles.header}>
            <View style={styles.titleCopy}>
              <Text numberOfLines={1} accessibilityRole="header" style={styles.title}>{file.name}</Text>
              <Text style={styles.meta}>{readableFileSize(file.size)}</Text>
            </View>
            <Pressable
              accessibilityLabel="Close image preview"
              accessibilityRole="button"
              hitSlop={8}
              style={({ pressed }) => [styles.closeButton, pressed && styles.pressed]}
              onPress={onClose}>
              <Text style={styles.closeText}>×</Text>
            </Pressable>
          </View>

          <View style={styles.preview}>
            {url ? (
              <Image
                accessibilityLabel={file.name}
                accessibilityRole="image"
                resizeMode="contain"
                source={{ uri: url }}
                style={styles.image}
                onError={() => {
                  setPreview({ key: requestKey, error: 'Could not display this image.' });
                }}
              />
            ) : error ? (
              <View accessibilityRole="alert" style={styles.status}>
                <Text style={styles.error}>{error}</Text>
                <Pressable
                  accessibilityLabel="Retry image preview"
                  accessibilityRole="button"
                  style={({ pressed }) => [styles.retryButton, pressed && styles.pressed]}
                  onPress={() => setRetry((value) => value + 1)}>
                  <Text style={styles.retryText}>Try again</Text>
                </Pressable>
              </View>
            ) : (
              <View accessibilityLabel="Loading full image" accessibilityRole="progressbar" style={styles.status}>
                <ActivityIndicator color="#3CD07D" size="large" />
                <Text style={styles.loading}>Loading full image…</Text>
              </View>
            )}
          </View>

          <View style={styles.footer}>
            <Text style={styles.footerHint}>Previewed privately in FroggyBot</Text>
            <Pressable
              accessibilityLabel="Open original image"
              accessibilityRole="button"
              accessibilityState={{ busy: opening, disabled: opening }}
              disabled={opening}
              style={({ pressed }) => [styles.originalButton, pressed && styles.pressed]}
              onPress={() => void openOriginal()}>
              <Text style={styles.originalText}>{opening ? 'Opening…' : 'Open original ↗'}</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(12,16,14,0.86)', paddingHorizontal: 12, alignItems: 'center', justifyContent: 'center' },
  modal: { flex: 1, width: '100%', maxWidth: 1120, maxHeight: 880, borderRadius: 20, overflow: 'hidden', backgroundColor: '#171A18' },
  header: { minHeight: 68, flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 18, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: '#434844' },
  titleCopy: { flex: 1, minWidth: 0 },
  title: { color: 'white', fontSize: 16, lineHeight: 21, fontWeight: '800' },
  meta: { color: '#AEB8B1', fontSize: 11, marginTop: 3 },
  closeButton: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 22, backgroundColor: '#2A2F2B' },
  closeText: { color: 'white', fontSize: 28, lineHeight: 30, fontWeight: '300', marginTop: -2 },
  preview: { flex: 1, minHeight: 220, alignItems: 'center', justifyContent: 'center', backgroundColor: '#0E100F' },
  image: { width: '100%', height: '100%' },
  status: { alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24 },
  error: { color: '#FFD0C8', fontSize: 14, textAlign: 'center' },
  retryButton: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 18, borderRadius: 12, backgroundColor: '#E8F3ED' },
  retryText: { color: '#006B35', fontSize: 13, fontWeight: '800' },
  loading: { color: '#C7D0CA', fontSize: 13 },
  footer: { minHeight: 66, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, paddingHorizontal: 18, borderTopWidth: StyleSheet.hairlineWidth, borderColor: '#434844' },
  footerHint: { flex: 1, color: '#99A49D', fontSize: 11 },
  originalButton: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 12 },
  originalText: { color: '#64D894', fontSize: 13, fontWeight: '800' },
  pressed: { opacity: 0.7 },
});
