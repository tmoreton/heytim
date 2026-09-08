import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Linking } from 'react-native';

import type { FrogBotApi } from '@/lib/api';
import {
  consumeInitialNotificationTarget,
  registerForReplyNotifications,
  subscribeToNotificationReplies,
} from '@/lib/notifications';
import type { ConversationSelection, Invitation } from '@/lib/types';

import { invitationFromUrl, invitationUrl } from '../invites/invitation-url';

type PendingSkill = { token: string; importKey: string };

const gmailStatusFromUrl = (url: string): 'connected' | 'error' | undefined => {
  try {
    const parsed = new URL(url);
    if (parsed.searchParams.get('oauth') !== 'gmail') return undefined;
    const status = parsed.searchParams.get('status');
    return status === 'connected' || status === 'error' ? status : undefined;
  } catch {
    return undefined;
  }
};

type Options = {
  api: FrogBotApi;
  demo: boolean;
  invitation?: Invitation;
  loadBootstrap: () => Promise<void>;
  openConversation: (selection: ConversationSelection) => void;
};

export function useConversationLinks({
  api,
  demo,
  invitation,
  loadBootstrap,
  openConversation,
}: Options) {
  const importedTokens = useRef(new Set<string>());
  const pushToken = useRef<string | null>(null);
  const [pendingSkill, setPendingSkill] = useState<PendingSkill>();

  useEffect(() => {
    if (demo) return;
    let active = true;
    const openNotification = (target: { botId?: string; groupId?: string }) => {
      if (!active) return;
      if (target.groupId) openConversation({ kind: 'group', id: target.groupId });
      else if (target.botId) openConversation({ kind: 'bot', id: target.botId });
    };

    registerForReplyNotifications()
      .then(async (token) => {
        if (!active || !token) return;
        pushToken.current = token;
        await api.registerPushToken(token);
      })
      .catch((value) => console.warn('Could not register for reply notifications.', value));
    consumeInitialNotificationTarget()
      .then((target) => {
        if (target) openNotification(target);
      })
      .catch((value) => console.warn('Could not read the initial notification.', value));
    const subscription = subscribeToNotificationReplies(openNotification);
    return () => {
      active = false;
      subscription.remove();
    };
  }, [api, demo, openConversation]);

  const importUrl = useCallback(async (url: string | null) => {
    if (!url) return;
    const gmailStatus = gmailStatusFromUrl(url);
    if (gmailStatus) {
      const resultKey = `oauth:${url}`;
      if (importedTokens.current.has(resultKey)) return;
      importedTokens.current.add(resultKey);
      if (gmailStatus === 'connected') {
        await loadBootstrap();
        Alert.alert('Gmail connected', 'Your Gmail Assistant is ready.');
      } else {
        Alert.alert('Gmail was not connected', 'Try again from Skills & tools.');
      }
      return;
    }
    const parsed = invitationFromUrl(url);
    if (!parsed) return;
    const { kind, token } = parsed;
    const importKey = `${kind}:${token}`;
    if (!token || importedTokens.current.has(importKey)) return;
    importedTokens.current.add(importKey);

    if (kind === 'skill') {
      setPendingSkill({ token, importKey });
      return;
    }
    try {
      if (kind === 'group') {
        const group = await api.joinGroup(token);
        await loadBootstrap();
        openConversation({ kind: 'group', id: group.id });
        Alert.alert('Group joined', `You are now in ${group.name}.`);
      } else {
        const bot = await api.importShare(token);
        await loadBootstrap();
        openConversation({ kind: 'bot', id: bot.id });
        Alert.alert('Bot added', `${bot.name} is now on your team.`);
      }
    } catch (value) {
      importedTokens.current.delete(importKey);
      const fallback = kind === 'group' ? 'The invite may have expired.' : 'The link may have expired.';
      Alert.alert(
        kind === 'group' ? 'Could not join group' : 'Could not open share',
        value instanceof Error ? value.message : fallback,
      );
    }
  }, [api, loadBootstrap, openConversation]);

  useEffect(() => {
    const initialInvitationUrl = invitation ? invitationUrl(invitation) : undefined;
    Linking.getInitialURL().then((url) => importUrl(initialInvitationUrl ?? url));
    const subscription = Linking.addEventListener('url', ({ url }) => importUrl(url));
    return () => subscription.remove();
  }, [importUrl, invitation]);

  const installSkill = useCallback(async () => {
    if (!pendingSkill) return;
    try {
      const skill = await api.importSkill(pendingSkill.token);
      await loadBootstrap();
      setPendingSkill(undefined);
      Alert.alert('Skill added', `${skill.name} is now in your library.`);
    } catch (value) {
      importedTokens.current.delete(pendingSkill.importKey);
      Alert.alert('Could not open share', value instanceof Error ? value.message : 'The link may have expired.');
    }
  }, [api, loadBootstrap, pendingSkill]);

  const dismissSkill = useCallback(() => {
    if (pendingSkill) importedTokens.current.delete(pendingSkill.importKey);
    setPendingSkill(undefined);
  }, [pendingSkill]);

  const unregisterPushToken = useCallback(async () => {
    if (pushToken.current) await api.unregisterPushToken(pushToken.current);
  }, [api]);

  return { pendingSkill, installSkill, dismissSkill, unregisterPushToken };
}
