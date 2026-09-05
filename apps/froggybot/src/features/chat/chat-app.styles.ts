import { Platform, StyleSheet } from 'react-native';

export const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: '#FBFBF9' },
  shell: { flex: 1, flexDirection: 'row', overflow: 'hidden' },
  wideDrawer: { width: 290 },
  mobileDrawerLayer: { position: 'absolute', inset: 0, zIndex: 20, flexDirection: 'row' },
  backdrop: { position: 'absolute', inset: 0, backgroundColor: 'rgba(18,18,15,0.28)' },
  mobileDrawer: {
    height: '100%',
    backgroundColor: '#F2F1ED',
    ...Platform.select({
      web: { boxShadow: '8px 0 24px rgba(0,0,0,0.2)' },
      default: { shadowColor: '#000', shadowOpacity: 0.2, shadowRadius: 24, shadowOffset: { width: 8, height: 0 } },
    }),
  },
});
