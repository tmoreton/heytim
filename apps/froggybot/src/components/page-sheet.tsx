import type { ReactNode } from 'react';
import { Modal, StyleSheet, View } from 'react-native';

import { colors } from '@/lib/theme';

type Props = {
  children: ReactNode;
  onClose: () => void;
};

/** Shared native presentation contract for full-page editors and settings. */
export function PageSheet({ children, onClose }: Props) {
  return (
    <Modal
      animationType="slide"
      presentationStyle="pageSheet"
      visible
      onRequestClose={onClose}>
      <View style={styles.page}>{children}</View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: colors.surface },
});
