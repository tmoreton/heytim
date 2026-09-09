import { useState } from 'react';
import { Stack, type ErrorBoundaryProps } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

export function ErrorBoundary({ error, retry }: ErrorBoundaryProps) {
  const [retrying, setRetrying] = useState(false);
  const tryAgain = async () => {
    if (retrying) return;
    setRetrying(true);
    try {
      await retry();
    } catch {
      setRetrying(false);
    }
  };

  return (
    <View accessibilityRole="alert" style={styles.errorPage}>
      <Text style={styles.errorTitle}>FroggyBot hit a snag</Text>
      <Text style={styles.errorMessage}>Your data is safe. Try reopening this screen.</Text>
      {__DEV__ ? <Text style={styles.errorDetail}>{error.message}</Text> : null}
      <Pressable
        accessibilityRole="button"
        disabled={retrying}
        onPress={() => void tryAgain()}
        style={({ pressed }) => [styles.retryButton, pressed && styles.retryPressed]}>
        {retrying ? <ActivityIndicator color="#FFFFFF" /> : <Text style={styles.retryText}>Try again</Text>}
      </Pressable>
    </View>
  );
}

export default function RootLayout() {
  return (
    <>
      <StatusBar style="dark" />
      <Stack screenOptions={{ headerShown: false, animation: 'fade' }} />
    </>
  );
}

const styles = StyleSheet.create({
  errorPage: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    padding: 28,
    backgroundColor: '#F4F2EC',
  },
  errorTitle: { color: '#171714', fontSize: 24, fontWeight: '800', textAlign: 'center' },
  errorMessage: { color: '#5F5B54', fontSize: 15, lineHeight: 22, textAlign: 'center' },
  errorDetail: { color: '#8A3D32', fontSize: 12, textAlign: 'center' },
  retryButton: {
    minWidth: 120,
    minHeight: 46,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 8,
    paddingHorizontal: 20,
    borderRadius: 14,
    backgroundColor: '#007A3D',
  },
  retryPressed: { opacity: 0.82 },
  retryText: { color: '#FFFFFF', fontSize: 15, fontWeight: '800' },
});
