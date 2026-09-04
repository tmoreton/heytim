import { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { AuthScreen } from '@/features/auth/auth-screen';
import { ChatApp } from '@/features/chat/chat-app';
import { hasSession } from '@/lib/auth';
import { cloudConfigured } from '@/lib/cloud';

type AppState = 'loading' | 'signedOut' | 'cloud' | 'demo';

export default function HomeScreen() {
  const [state, setState] = useState<AppState>(cloudConfigured ? 'loading' : 'signedOut');

  useEffect(() => {
    if (!cloudConfigured) return;
    hasSession().then((signedIn) => setState(signedIn ? 'cloud' : 'signedOut'));
  }, []);

  if (state === 'loading') {
    return (
      <View style={styles.loading}>
        <ActivityIndicator color="#007A3D" />
      </View>
    );
  }
  if (state === 'signedOut') {
    return <AuthScreen cloudReady={cloudConfigured} onSignedIn={() => setState('cloud')} onDemo={() => setState('demo')} />;
  }
  return <ChatApp demo={state === 'demo'} onSignedOut={() => setState('signedOut')} />;
}

const styles = StyleSheet.create({
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: '#F4F2EC' },
});
