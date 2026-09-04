import { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { AuthScreen } from '@/features/auth/auth-screen';
import { ChatApp } from '@/features/chat/chat-app';
import { hasSession } from '@/lib/auth';
import { cloudConfigured } from '@/lib/cloud';
import type { Invitation, InvitePreview } from '@/lib/types';

type AppState = 'loading' | 'signedOut' | 'cloud' | 'demo';

type Props = {
  invitation?: Invitation;
  invitePreview?: InvitePreview;
  preview?: boolean;
};

export function AppEntry({ invitation, invitePreview, preview = false }: Props = {}) {
  const [state, setState] = useState<AppState>(preview ? 'demo' : cloudConfigured ? 'loading' : 'signedOut');

  useEffect(() => {
    if (!cloudConfigured || preview) return;
    let active = true;
    hasSession().then((signedIn) => {
      if (active) setState(signedIn ? 'cloud' : 'signedOut');
    });
    return () => {
      active = false;
    };
  }, [preview]);

  if (state === 'loading') {
    return (
      <View style={styles.loading}>
        <ActivityIndicator color="#007A3D" />
      </View>
    );
  }
  if (state === 'signedOut') {
    return (
      <AuthScreen
        cloudReady={cloudConfigured}
        invitation={invitation}
        invitePreview={invitePreview}
        onSignedIn={() => setState('cloud')}
        onDemo={() => setState('demo')}
      />
    );
  }
  return (
    <ChatApp
      demo={state === 'demo'}
      invitation={invitation}
      onSignedOut={() => setState('signedOut')}
    />
  );
}

const styles = StyleSheet.create({
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: '#F4F2EC' },
});
