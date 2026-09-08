import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';

import { useModalFocus } from './use-modal-focus';

type ActionSheetOption = {
  label: string;
  onPress: () => void;
  destructive?: boolean;
};

type Props = {
  visible: boolean;
  title: string;
  message?: string;
  options: ActionSheetOption[];
  onClose: () => void;
};

export function ActionSheet({ visible, title, message, options, onClose }: Props) {
  const modalRef = useModalFocus(onClose, visible);
  if (!visible) return null;
  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose}>
      <View
        ref={modalRef}
        accessibilityLabel={title}
        accessibilityViewIsModal
        aria-modal
        role="alertdialog"
        style={styles.layer}>
        <Pressable accessibilityLabel="Close menu" accessibilityRole="button" style={styles.backdrop} onPress={onClose} />
        <View style={styles.sheet}>
          <Text accessibilityRole="header" style={styles.title}>
            {title}
          </Text>
          {message ? <Text style={styles.message}>{message}</Text> : null}
          <View style={styles.options}>
            {options.map((option) => (
              <Pressable
                key={option.label}
                accessibilityRole="button"
                style={({ pressed }) => [styles.option, pressed && styles.pressed]}
                onPress={() => {
                  onClose();
                  option.onPress();
                }}>
                <Text style={[styles.optionText, option.destructive && styles.destructive]}>{option.label}</Text>
              </Pressable>
            ))}
          </View>
          <Pressable
            accessibilityRole="button"
            style={({ pressed }) => [styles.cancel, pressed && styles.pressed]}
            onPress={onClose}>
            <Text style={styles.cancelText}>Cancel</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  layer: { flex: 1, justifyContent: 'flex-end', padding: 12 },
  backdrop: { ...StyleSheet.absoluteFill, backgroundColor: 'rgba(18,18,15,0.32)' },
  sheet: {
    alignSelf: 'center',
    width: '100%',
    maxWidth: 430,
    padding: 14,
    borderRadius: 24,
    backgroundColor: '#F8F7F3',
  },
  title: { color: '#1D1C18', fontSize: 18, fontWeight: '800', textAlign: 'center', marginTop: 5 },
  message: { color: '#77736B', fontSize: 13, lineHeight: 19, textAlign: 'center', margin: 9 },
  options: { marginTop: 8, overflow: 'hidden', borderRadius: 16, borderWidth: 1, borderColor: '#E0DDD5' },
  option: {
    minHeight: 52,
    alignItems: 'center',
    justifyContent: 'center',
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderColor: '#E0DDD5',
    backgroundColor: '#FFFFFF',
  },
  optionText: { color: '#007A3D', fontSize: 16, fontWeight: '700' },
  destructive: { color: '#A53A32' },
  cancel: { minHeight: 52, alignItems: 'center', justifyContent: 'center', marginTop: 10, borderRadius: 16, backgroundColor: '#FFFFFF' },
  cancelText: { color: '#3B3933', fontSize: 16, fontWeight: '700' },
  pressed: { opacity: 0.72 },
});
