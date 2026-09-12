import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Linking } from 'react-native';

import type { FrogBotApi } from '@froggybot/client';
import {
  consumeInitialNotificationTarget,
  registerForReplyNotifications,
  subscribeToNotificationReplies,
} from './notifications';
import type { ConversationSelection, Invitation } from '@froggybot/contracts';

import { invitationFromUrl, invitationUrl } from '@froggybot/client';

type PendingSkill = { token: string; importKey: string };

const connectionStatusFromUrl = (
  url: string,
): { providerId: string; status: 'connected' | 'error' } | undefined => {
  try {
    const parsed = new URL(url);
    const providerId = parsed.searchParams.get('connection') ?? parsed.searchParams.get('oauth');
    if (!providerId) return undefined;
    const status = parsed.searchParams.get('status');
    return status === 'connected' || status === 'error' ? { providerId, status } : undefined;
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
    const connection = connectionStatusFromUrl(url);
    if (connection) {
      const resultKey = `connection:${url}`;
      if (importedTokens.current.has(resultKey)) return;
      importedTokens.current.add(resultKey);
      if (connection.status === 'connected') {
        await loadBootstrap();
        Alert.alert('Account connected', 'The account is ready for your FroggyBots.');
      } else {
        Alert.alert('Account was not connected', 'Try again from Account → Connections.');
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
    let active = true;
    const reportImportError = (value: unknown) => {
      if (!active) return;
      Alert.alert(
        'Could not open link',
        value instanceof Error ? value.message : 'Please try opening the link again.',
      );
    };
    Linking.getInitialURL()
      .then((url) => importUrl(initialInvitationUrl ?? url))
      .catch(reportImportError);
    const subscription = Linking.addEventListener('url', ({ url }) => {
      void importUrl(url).catch(reportImportError);
    });
    return () => {
      active = false;
      subscription.remove();
    };
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
