import { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { AuthScreen } from '@/features/auth/auth-screen';
import { ChatApp } from '@/features/chat/chat-app';
import { hasSession } from '@froggybot/expo-client';
import { cloudConfigured } from '@/lib/cloud';
import type { CapabilitySelection, Invitation, InvitePreview } from '@froggybot/contracts';
import { previewEnabled } from '@froggybot/preview-api';

type AppState = 'loading' | 'signedOut' | 'cloud' | 'demo';

type Props = {
  invitation?: Invitation;
  invitePreview?: InvitePreview;
  initialCapability?: CapabilitySelection;
  initialBotTemplateId?: string;
  preview?: boolean;
};

export function AppEntry({ invitation, invitePreview, initialCapability, initialBotTemplateId, preview = false }: Props = {}) {
  const localPreview = preview && previewEnabled;
  const [state, setState] = useState<AppState>(localPreview ? 'demo' : cloudConfigured ? 'loading' : 'signedOut');

  useEffect(() => {
    if (!cloudConfigured || localPreview) return;
    let active = true;
    hasSession().then((signedIn) => {
      if (active) setState(signedIn ? 'cloud' : 'signedOut');
    });
    return () => {
      active = false;
    };
  }, [localPreview]);

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
        previewAvailable={previewEnabled}
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
      initialBotTemplateId={initialBotTemplateId}
      initialCapability={initialCapability}
      onSignedOut={() => setState('signedOut')}
    />
  );
}

const styles = StyleSheet.create({
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: '#F4F2EC' },
});
