import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ExpoSpeechRecognitionModule, useSpeechRecognitionEvent } from 'expo-speech-recognition';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  KeyboardAvoidingView,
  Linking,
  Platform,
  Pressable,
  Share,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ActionSheet } from '@/components/action-sheet';
import { BotAvatar } from '@/components/bot-avatar';
import { GroupAvatar } from '@/components/participant-avatar';
import { endSession } from '@/lib/auth';
import { createApi } from '@/lib/api';
import {
  consumeInitialNotificationTarget,
  registerForReplyNotifications,
  subscribeToNotificationReplies,
} from '@/lib/notifications';
import type { Bootstrap, Bot, BotDraft, Group, GroupDraft, GroupMember, Invitation, Message } from '@/lib/types';

import { BotEditor } from './bot-editor';
import { ConversationDrawer, type ConversationSelection as Selection } from './conversation-drawer';
import { ConversationHeader } from './conversation-header';
import { GroupEditor } from './group-editor';
import { MessageBubble } from './message-bubble';
import { ALL_BOTS_REPLY_TARGET, MessageComposer } from './message-composer';
import { SkillLibrary } from './skill-library';
import { invitationFromUrl } from '../invites/invitation-url';

type Props = {
  demo: boolean;
  invitation?: Invitation;
  onSignedOut: () => void;
};

const MESSAGE_REFRESH_MS = 900;

export function ChatApp({ demo, invitation, onSignedOut }: Props) {
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const wide = width >= 760;
  const api = useMemo(() => createApi(demo), [demo]);
  const list = useRef<FlatList<Message>>(null);
  const importedTokens = useRef(new Set<string>());
  const messageRequest = useRef(0);
  const dictationBase = useRef('');
  const pushToken = useRef<string | null>(null);
  const [data, setData] = useState<Bootstrap>();
  const [selection, setSelection] = useState<Selection>();
  const [messages, setMessages] = useState<Message[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(wide);
  const [search, setSearch] = useState('');
  const [draft, setDraft] = useState('');
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [sending, setSending] = useState(false);
  const [listening, setListening] = useState(false);
  const [error, setError] = useState('');
  const [editor, setEditor] = useState<'new' | 'edit' | undefined>();
  const [groupEditor, setGroupEditor] = useState<'new' | 'edit' | undefined>();
  const [skillLibraryOpen, setSkillLibraryOpen] = useState(false);
  const [botMenuOpen, setBotMenuOpen] = useState(false);
  const [pendingBotAction, setPendingBotAction] = useState<'clear' | 'delete'>();
  const [pendingSkillInvite, setPendingSkillInvite] = useState<{ token: string; importKey: string }>();
  const [replyBotId, setReplyBotId] = useState<string | null>();

  const selectedBot = selection?.kind === 'bot' ? data?.bots.find((bot) => bot.id === selection.id) : undefined;
  const selectedGroup = selection?.kind === 'group' ? data?.groups.find((group) => group.id === selection.id) : undefined;
  const selected = selectedBot ?? selectedGroup;
  const pending = messages.some((message) => message.status === 'pending');
  const pendingBotCount = messages.filter(
    (message) => message.status === 'pending' && message.authorType === 'bot',
  ).length;
  const activeReplyBotId = replyBotId === null
    ? undefined
    : replyBotId === ALL_BOTS_REPLY_TARGET && selectedGroup?.bots.length
      ? ALL_BOTS_REPLY_TARGET
    : selectedGroup?.bots.some((bot) => bot.id === replyBotId)
      ? replyBotId
      : selectedGroup && selectedGroup.bots.length > 1
        ? ALL_BOTS_REPLY_TARGET
        : selectedGroup?.bots[0]?.id;

  const chooseAvailableSelection = useCallback((next: Bootstrap, current?: Selection): Selection | undefined => {
    if (current?.kind === 'bot' && next.bots.some((bot) => bot.id === current.id)) return current;
    if (current?.kind === 'group' && next.groups.some((group) => group.id === current.id)) return current;
    if (next.groups[0]) return { kind: 'group', id: next.groups[0].id };
    if (next.bots[0]) return { kind: 'bot', id: next.bots[0].id };
    return undefined;
  }, []);

  useSpeechRecognitionEvent('start', () => setListening(true));
  useSpeechRecognitionEvent('end', () => setListening(false));
  useSpeechRecognitionEvent('result', (event) => {
    const transcript = event.results[0]?.transcript?.trim();
    if (!transcript) return;
    setDraft(dictationBase.current ? `${dictationBase.current} ${transcript}` : transcript);
  });
  useSpeechRecognitionEvent('error', (event) => {
    setListening(false);
    if (event.error === 'aborted' || event.error === 'no-speech') return;
    if (event.error === 'not-allowed') {
      setError('Allow microphone access in Settings to dictate messages.');
      return;
    }
    if (event.error === 'language-not-supported') {
      setError('On-device dictation does not support this iPhone language. Try changing the keyboard language in Settings.');
      return;
    }
    if (event.error === 'service-not-allowed') {
      setError('Turn on Siri & Dictation and download this language in iPhone Settings, then try again.');
      return;
    }
    setError('On-device dictation stopped unexpectedly. Please try again.');
  });

  const loadBootstrap = useCallback(async () => {
    try {
      const next = await api.bootstrap();
      setData(next);
      setSelection((current) => chooseAvailableSelection(next, current));
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not load your bots.');
    }
  }, [api, chooseAvailableSelection]);

  const loadMessages = useCallback(async () => {
    if (!selection) return;
    const requestId = ++messageRequest.current;
    try {
      const next = selection.kind === 'group'
        ? await api.groupMessages(selection.id)
        : await api.messages(selection.id);
      if (requestId === messageRequest.current) {
        setMessages(next);
        setError('');
      }
    } catch (value) {
      if (requestId === messageRequest.current) {
        setError(value instanceof Error ? value.message : 'Could not load this conversation.');
      }
    } finally {
      if (requestId === messageRequest.current) setLoadingMessages(false);
    }
  }, [api, selection]);

  useEffect(() => {
    let active = true;
    api
      .bootstrap()
      .then((next) => {
        if (!active) return;
        setData(next);
        setLoadingMessages(Boolean(next.groups[0] ?? next.bots[0]));
        setSelection((current) => chooseAvailableSelection(next, current));
      })
      .catch((value) => {
        if (active) setError(value instanceof Error ? value.message : 'Could not load your bots.');
      });
    return () => {
      active = false;
    };
  }, [api, chooseAvailableSelection]);

  useEffect(() => {
    if (!selection) return;
    let active = true;
    const requestId = ++messageRequest.current;
    const request = selection.kind === 'group' ? api.groupMessages(selection.id) : api.messages(selection.id);
    request
      .then((next) => {
        if (!active || requestId !== messageRequest.current) return;
        setMessages(next);
        setError('');
      })
      .catch((value) => {
        if (active && requestId === messageRequest.current) {
          setError(value instanceof Error ? value.message : 'Could not load this conversation.');
        }
      })
      .finally(() => {
        if (active && requestId === messageRequest.current) setLoadingMessages(false);
      });
    return () => {
      active = false;
    };
  }, [api, selection]);

  useEffect(() => {
    if (!pending) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      await loadMessages();
      if (active) timer = setTimeout(poll, MESSAGE_REFRESH_MS);
    };
    timer = setTimeout(poll, MESSAGE_REFRESH_MS);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [loadMessages, pending]);

  useEffect(() => {
    if (demo) return;
    let active = true;
    const openConversation = (target: { botId?: string; groupId?: string }) => {
      if (!active) return;
      const next = target.groupId
        ? { kind: 'group' as const, id: target.groupId }
        : target.botId
          ? { kind: 'bot' as const, id: target.botId }
          : undefined;
      if (!next) return;
      setMessages([]);
      setLoadingMessages(true);
      setSelection(next);
      setDrawerOpen(false);
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
        if (target) openConversation(target);
      })
      .catch((value) => console.warn('Could not read the initial notification.', value));
    const subscription = subscribeToNotificationReplies(openConversation);
    return () => {
      active = false;
      subscription.remove();
    };
  }, [api, demo]);

  const importUrl = useCallback(
    async (url: string | null) => {
      if (!url) return;
      const parsedInvitation = invitationFromUrl(url);
      if (!parsedInvitation) return;
      const { kind, token } = parsedInvitation;
      const importKey = `${kind}:${token}`;
      if (!token || importedTokens.current.has(importKey)) return;
      importedTokens.current.add(importKey);
      if (kind === 'group') {
        try {
          const group = await api.joinGroup(token);
          await loadBootstrap();
          setMessages([]);
          setLoadingMessages(true);
          setSelection({ kind: 'group', id: group.id });
          setDrawerOpen(false);
          Alert.alert('Group joined', `You are now in ${group.name}.`);
        } catch (value) {
          importedTokens.current.delete(importKey);
          Alert.alert('Could not join group', value instanceof Error ? value.message : 'The invite may have expired.');
        }
        return;
      }
      if (kind === 'skill') {
        setPendingSkillInvite({ token, importKey });
        return;
      }
      try {
        const bot = await api.importShare(token);
        await loadBootstrap();
        setMessages([]);
        setLoadingMessages(true);
        setSelection({ kind: 'bot', id: bot.id });
        Alert.alert('Bot added', `${bot.name} is now on your team.`);
      } catch (value) {
        importedTokens.current.delete(importKey);
        Alert.alert('Could not open share', value instanceof Error ? value.message : 'The link may have expired.');
      }
    },
    [api, loadBootstrap],
  );

  useEffect(() => {
    const invitationUrl = invitation
      ? `frogbot://invite?kind=${invitation.kind}&token=${encodeURIComponent(invitation.token)}`
      : undefined;
    Linking.getInitialURL().then((url) => importUrl(invitationUrl ?? url));
    const subscription = Linking.addEventListener('url', ({ url }) => importUrl(url));
    return () => subscription.remove();
  }, [importUrl, invitation]);

  const selectBot = (bot: Bot) => {
    if (listening) ExpoSpeechRecognitionModule.abort();
    setMessages([]);
    setLoadingMessages(true);
    setSelection({ kind: 'bot', id: bot.id });
    if (!wide) setDrawerOpen(false);
  };

  const selectGroup = (group: Group) => {
    if (listening) ExpoSpeechRecognitionModule.abort();
    setMessages([]);
    setLoadingMessages(true);
    setSelection({ kind: 'group', id: group.id });
    if (!wide) setDrawerOpen(false);
  };

  const saveBot = async (value: BotDraft) => {
    const saved = await api.saveBot(value, editor === 'edit' ? selectedBot?.id : undefined);
    setData((current) => {
      if (!current) return current;
      const exists = current.bots.some((bot) => bot.id === saved.id);
      return { ...current, bots: exists ? current.bots.map((bot) => (bot.id === saved.id ? saved : bot)) : [saved, ...current.bots] };
    });
    setMessages([]);
    setLoadingMessages(true);
    setSelection({ kind: 'bot', id: saved.id });
  };

  const saveGroup = async (value: GroupDraft) => {
    const saved = await api.saveGroup(value, groupEditor === 'edit' ? selectedGroup?.id : undefined);
    setData((current) => {
      if (!current) return current;
      const exists = current.groups.some((group) => group.id === saved.id);
      return {
        ...current,
        groups: exists ? current.groups.map((group) => (group.id === saved.id ? saved : group)) : [saved, ...current.groups],
      };
    });
    setMessages([]);
    setLoadingMessages(true);
    setSelection({ kind: 'group', id: saved.id });
  };

  const send = async () => {
    const text = draft.trim();
    if (!text || !selected || sending || pending) return;
    setSending(true);
    if (listening) ExpoSpeechRecognitionModule.stop();
    setDraft('');
    try {
      if (selectedGroup) await api.sendGroupMessage(selectedGroup.id, text, activeReplyBotId);
      else if (selectedBot) await api.sendMessage(selectedBot, text);
      await loadMessages();
    } catch (value) {
      setDraft(text);
      setError(value instanceof Error ? value.message : 'Could not send that message.');
    } finally {
      setSending(false);
    }
  };

  const toggleDictation = async () => {
    if (listening) {
      ExpoSpeechRecognitionModule.stop();
      return;
    }
    if (Platform.OS !== 'ios') return;
    try {
      const permissions = await ExpoSpeechRecognitionModule.requestMicrophonePermissionsAsync();
      if (!permissions.granted) {
        setError('Allow microphone access in Settings to dictate messages.');
        return;
      }
      const deviceLocale = (Intl.DateTimeFormat().resolvedOptions().locale || 'en-US').replaceAll('_', '-');
      const { locales } = await ExpoSpeechRecognitionModule.getSupportedLocales({});
      const language = deviceLocale.split('-')[0];
      const locale = locales.find((value) => value.toLowerCase() === deviceLocale.toLowerCase())
        ?? locales.find((value) => value.toLowerCase().startsWith(`${language.toLowerCase()}-`))
        ?? 'en-US';
      dictationBase.current = draft.trimEnd();
      setError('');
      ExpoSpeechRecognitionModule.start({
        lang: locale,
        interimResults: true,
        continuous: false,
        requiresOnDeviceRecognition: true,
        addsPunctuation: true,
        iosTaskHint: 'dictation',
        recordingOptions: { persist: false },
      });
    } catch {
      setListening(false);
      setError('On-device dictation could not start. Please check the app permissions in Settings.');
    }
  };

  const share = (scope: 'bot' | 'chat') => {
    if (!selectedBot) return;
    api
      .share(selectedBot.id, scope)
      .then((url) =>
        Share.share({
          title: `Share ${selectedBot.name}`,
          message: scope === 'chat' ? `Open my conversation with ${selectedBot.name}: ${url}` : `Add ${selectedBot.name} to FrogBot: ${url}`,
          url,
        }),
      )
      .catch((value) => Alert.alert('Could not share', value instanceof Error ? value.message : 'Please try again.'));
  };

  const showBotOptions = () => {
    setBotMenuOpen(true);
  };

  const refreshAfterDeletion = async () => {
    const next = await api.bootstrap();
    const nextSelection = chooseAvailableSelection(next, selection);
    messageRequest.current += 1;
    setData(next);
    setMessages([]);
    setError('');
    setSelection(nextSelection);
    setLoadingMessages(Boolean(nextSelection));
  };

  const runBotDeletion = async () => {
    if (!selectedBot || !pendingBotAction) return;
    if (listening) ExpoSpeechRecognitionModule.abort();
    try {
      if (pendingBotAction === 'clear') {
        await api.clearBotChat(selectedBot.id);
        const next = await api.bootstrap();
        messageRequest.current += 1;
        setData(next);
        setMessages([]);
        setError('');
        setLoadingMessages(false);
        return;
      }
      await api.deleteBot(selectedBot.id);
      await refreshAfterDeletion();
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not delete that conversation.');
    }
  };

  const installSharedSkill = async () => {
    if (!pendingSkillInvite) return;
    const { token, importKey } = pendingSkillInvite;
    importedTokens.current.add(importKey);
    try {
      const skill = await api.importSkill(token);
      await loadBootstrap();
      Alert.alert('Skill added', `${skill.name} is now in your library.`);
    } catch (value) {
      importedTokens.current.delete(importKey);
      Alert.alert('Could not open share', value instanceof Error ? value.message : 'The link may have expired.');
    }
  };

  const shareGroup = async () => {
    if (!selectedGroup) throw new Error('Choose a group first.');
    return api.shareGroup(selectedGroup.id);
  };

  const removeGroupMember = async (member: GroupMember) => {
    if (!selectedGroup) return;
    await api.removeGroupMember(selectedGroup.id, member.id);
    const next = await api.bootstrap();
    setData(next);
    setSelection((current) => chooseAvailableSelection(next, current));
  };

  const deleteGroup = async () => {
    if (!selectedGroup) return;
    if (listening) ExpoSpeechRecognitionModule.abort();
    await api.deleteGroup(selectedGroup.id);
    await refreshAfterDeletion();
  };

  const signOut = async () => {
    if (listening) ExpoSpeechRecognitionModule.abort();
    if (!demo) {
      const token = pushToken.current;
      if (token) {
        try {
          await api.unregisterPushToken(token);
        } catch (value) {
          console.warn('Could not unregister the push token.', value);
        }
      }
      await endSession();
    }
    onSignedOut();
  };

  const drawer = (
    <ConversationDrawer
      bots={data?.bots ?? []}
      groups={data?.groups ?? []}
      selection={selection}
      search={search}
      demo={demo}
      wide={wide}
      topInset={insets.top}
      bottomInset={insets.bottom}
      onSearchChange={setSearch}
      onSelectBot={selectBot}
      onSelectGroup={selectGroup}
      onCreateBot={() => setEditor('new')}
      onCreateGroup={() => setGroupEditor('new')}
      onOpenSkills={() => setSkillLibraryOpen(true)}
      onClose={() => setDrawerOpen(false)}
      onSignOut={signOut}
    />
  );

  return (
    <View style={styles.safeArea}>
      <KeyboardAvoidingView style={styles.safeArea} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.shell}>
          {wide && drawerOpen ? <View style={styles.wideDrawer}>{drawer}</View> : null}
          <View style={styles.conversation}>
            <ConversationHeader
              bot={selectedBot}
              group={selectedGroup}
              listening={listening}
              pending={pending}
              pendingBotCount={pendingBotCount}
              topInset={insets.top}
              onToggleDrawer={() => setDrawerOpen((value) => !value)}
              onEditBot={() => setEditor('edit')}
              onEditGroup={() => setGroupEditor('edit')}
              onOpenBotMenu={showBotOptions}
            />

            {error ? (
              <Pressable
                accessibilityLabel={`${error}. Dismiss`}
                accessibilityRole="alert"
                style={styles.errorBar}
                onPress={() => setError('')}>
                <Text numberOfLines={2} style={styles.errorText}>
                  {error}
                </Text>
                <Text style={styles.errorDismiss}>×</Text>
              </Pressable>
            ) : null}

            {loadingMessages ? (
              <View style={styles.center}>
                <ActivityIndicator color="#007A3D" />
              </View>
            ) : (
              <FlatList
                ref={list}
                data={messages}
                keyExtractor={(message) => message.id}
                contentContainerStyle={[styles.messages, messages.length === 0 && styles.emptyMessages]}
                onContentSizeChange={() => list.current?.scrollToEnd({ animated: true })}
                ListEmptyComponent={
                  selectedGroup ? (
                    <View style={styles.emptyState}>
                      <GroupAvatar group={selectedGroup} size={76} />
                      <Text style={styles.emptyTitle}>Welcome to {selectedGroup.name}</Text>
                      <Text style={styles.emptyCopy}>Write to everyone, ask one FrogBot, or let the whole team collaborate in one shared round.</Text>
                    </View>
                  ) : selectedBot ? (
                    <View style={styles.emptyState}>
                      <BotAvatar color={selectedBot.color} name={selectedBot.name} size={70} />
                      <Text style={styles.emptyTitle}>Talk to {selectedBot.name}</Text>
                      <Text style={styles.emptyCopy}>{selectedBot.tagline || 'Start with the outcome you want.'}</Text>
                    </View>
                  ) : null
                }
                renderItem={({ item }) => <MessageBubble message={item} groupMode={Boolean(selectedGroup)} />}
              />
            )}

            <MessageComposer
              selectedName={selected?.name}
              group={selectedGroup}
              activeReplyBotId={activeReplyBotId}
              draft={draft}
              listening={listening}
              pending={pending}
              sending={sending}
              bottomInset={insets.bottom}
              onDraftChange={setDraft}
              onReplyTargetChange={setReplyBotId}
              onToggleDictation={toggleDictation}
              onSend={send}
            />
          </View>

          {!wide && drawerOpen ? (
            <View style={styles.mobileDrawerLayer}>
              <Pressable style={styles.backdrop} onPress={() => setDrawerOpen(false)} />
              <View style={[styles.mobileDrawer, { width: Math.min(width * 0.86, 340) }]}>{drawer}</View>
            </View>
          ) : null}
        </View>
      </KeyboardAvoidingView>

      {editor ? (
        <BotEditor
          key={`${editor}-${selectedBot?.id ?? 'new'}`}
          bot={editor === 'edit' ? selectedBot : undefined}
          tools={data?.tools ?? []}
          skills={data?.skills ?? []}
          onClose={() => setEditor(undefined)}
          onSave={saveBot}
        />
      ) : null}
      {groupEditor ? (
        <GroupEditor
          key={`${groupEditor}-${selectedGroup?.id ?? 'new'}`}
          group={groupEditor === 'edit' ? selectedGroup : undefined}
          bots={data?.bots ?? []}
          onClose={() => setGroupEditor(undefined)}
          onSave={saveGroup}
          onShare={shareGroup}
          onRemoveMember={removeGroupMember}
          onDelete={deleteGroup}
        />
      ) : null}
      {skillLibraryOpen ? (
        <SkillLibrary
          skills={data?.skills ?? []}
          tools={data?.tools ?? []}
          onClose={() => setSkillLibraryOpen(false)}
          onLoad={api.skill}
          onSave={api.saveSkill}
          onShare={api.shareSkill}
          onChanged={loadBootstrap}
        />
      ) : null}
      <ActionSheet
        visible={botMenuOpen}
        title={selectedBot?.name ?? 'FrogBot'}
        message="Share this FrogBot, clear its conversation, or remove it from your team."
        options={[
          { label: 'Share bot setup', onPress: () => share('bot') },
          { label: 'Share conversation', onPress: () => share('chat') },
          { label: 'Clear conversation', destructive: true, onPress: () => setPendingBotAction('clear') },
          { label: 'Delete bot', destructive: true, onPress: () => setPendingBotAction('delete') },
        ]}
        onClose={() => setBotMenuOpen(false)}
      />
      <ActionSheet
        visible={Boolean(pendingBotAction)}
        title={pendingBotAction === 'delete' ? `Delete ${selectedBot?.name ?? 'this bot'}?` : 'Clear this conversation?'}
        message={
          pendingBotAction === 'delete'
            ? 'This permanently deletes the FrogBot, its direct chat, and removes it from your groups.'
            : 'This permanently deletes every message in this direct chat but keeps the FrogBot.'
        }
        options={[
          {
            label: pendingBotAction === 'delete' ? 'Delete bot' : 'Clear conversation',
            destructive: true,
            onPress: runBotDeletion,
          },
        ]}
        onClose={() => setPendingBotAction(undefined)}
      />
      <ActionSheet
        visible={Boolean(pendingSkillInvite)}
        title="Install shared skill?"
        message="Skills change how your bots work. Only install skills from people you trust."
        options={[{ label: 'Install skill', onPress: installSharedSkill }]}
        onClose={() => {
          if (pendingSkillInvite) importedTokens.current.delete(pendingSkillInvite.importKey);
          setPendingSkillInvite(undefined);
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: '#FBFBF9' },
  shell: { flex: 1, flexDirection: 'row', overflow: 'hidden' },
  wideDrawer: { width: 290 },
  conversation: { flex: 1, backgroundColor: '#FBFBF9' },
  errorBar: { minHeight: 44, backgroundColor: '#FCECE8', paddingHorizontal: 14, flexDirection: 'row', alignItems: 'center', gap: 10 },
  errorText: { flex: 1, color: '#9E342A', fontSize: 13 },
  errorDismiss: { color: '#9E342A', fontSize: 21 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  messages: { paddingHorizontal: 14, paddingTop: 24, paddingBottom: 18, maxWidth: 780, width: '100%', alignSelf: 'center' },
  emptyMessages: { flexGrow: 1, justifyContent: 'center' },
  emptyState: { alignItems: 'center', paddingHorizontal: 34, marginTop: -30 },
  emptyTitle: { color: '#201F1B', fontSize: 22, fontWeight: '800', letterSpacing: -0.4, marginTop: 18 },
  emptyCopy: { color: '#827E76', fontSize: 14, lineHeight: 20, textAlign: 'center', marginTop: 7, maxWidth: 340 },
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
  pressed: { opacity: 0.7 },
});
