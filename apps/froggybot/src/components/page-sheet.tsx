import type { ReactNode } from 'react';
import { Modal, StyleSheet, View } from 'react-native';

import { colors } from '@/lib/theme';

import { useModalFocus } from './use-modal-focus';

type Props = {
  children: ReactNode;
  accessibilityLabel?: string;
  onClose: () => void;
};

/** Shared native presentation contract for full-page editors and settings. */
export function PageSheet({ children, accessibilityLabel = 'FroggyBot dialog', onClose }: Props) {
  const modalRef = useModalFocus(onClose);
  return (
    <Modal
      animationType="slide"
      presentationStyle="pageSheet"
      visible
      onRequestClose={onClose}>
      <View
        ref={modalRef}
        accessibilityLabel={accessibilityLabel}
        accessibilityViewIsModal
        aria-modal
        role="dialog"
        style={styles.page}>
        {children}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: colors.surface },
});
