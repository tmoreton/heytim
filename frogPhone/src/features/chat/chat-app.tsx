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
  ScrollView,
  SectionList,
  Share,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AgentActivity } from '@/components/agent-activity';
import { BotAvatar } from '@/components/bot-avatar';
import { MessageMarkdown } from '@/components/message-markdown';
import { GroupAvatar, PersonAvatar } from '@/components/participant-avatar';
import { endSession } from '@/lib/auth';
import { createApi } from '@/lib/api';
import {
  consumeInitialNotificationTarget,
  registerForReplyNotifications,
  subscribeToNotificationReplies,
} from '@/lib/notifications';
import type { Bootstrap, Bot, BotDraft, Group, GroupDraft, GroupMember, Invitation, InviteKind, Message } from '@/lib/types';

import { BotEditor } from './bot-editor';
import { GroupEditor } from './group-editor';
import { SkillLibrary } from './skill-library';

type Props = {
  demo: boolean;
  invitation?: Invitation;
  onSignedOut: () => void;
};

type Selection = { kind: 'bot' | 'group'; id: string };
type DrawerItem = { kind: 'group'; value: Group } | { kind: 'bot'; value: Bot };
const ALL_BOTS_REPLY_TARGET = 'all';
const MESSAGE_REFRESH_MS = 900;

const friendlyDate = (value: string) => {
  const date = new Date(value);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) return 'Now';
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
};

export function ChatApp({ demo, invitation, onSignedOut }: Props) {
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const wide = width >= 760;
  const api = useMemo(() => createApi(demo), [demo]);
  const list = useRef<FlatList<Message>>(null);
  const importedTokens = useRef(new Set<string>());
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
    try {
      setMessages(
        selection.kind === 'group' ? await api.groupMessages(selection.id) : await api.messages(selection.id),
      );
      setError('');
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not load this conversation.');
    } finally {
      setLoadingMessages(false);
    }
  }, [api, selection]);

  useEffect(() => {
    api
      .bootstrap()
      .then((next) => {
        setData(next);
        setSelection((current) => chooseAvailableSelection(next, current));
      })
      .catch((value) => setError(value instanceof Error ? value.message : 'Could not load your bots.'));
  }, [api, chooseAvailableSelection]);

  useEffect(() => {
    if (!selection) return;
    const request = selection.kind === 'group' ? api.groupMessages(selection.id) : api.messages(selection.id);
    request
      .then((next) => {
        setMessages(next);
        setError('');
      })
      .catch((value) => setError(value instanceof Error ? value.message : 'Could not load this conversation.'))
      .finally(() => setLoadingMessages(false));
  }, [api, selection]);

  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(loadMessages, MESSAGE_REFRESH_MS);
    return () => clearInterval(timer);
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
      let token = '';
      let kind: InviteKind = 'bot';
      try {
        const parsed = new URL(url);
        const queryKind = parsed.searchParams.get('kind');
        if (queryKind === 'bot' || queryKind === 'chat' || queryKind === 'group' || queryKind === 'skill') {
          kind = queryKind;
        } else if (parsed.hostname === 'group' || parsed.pathname.includes('/group/')) kind = 'group';
        else if (parsed.hostname === 'skill' || parsed.pathname.includes('/skill/')) kind = 'skill';
        token = parsed.searchParams.get('token') ?? (
          parsed.hostname === 'share' || parsed.hostname === 'skill' || parsed.hostname === 'group'
            ? parsed.pathname.replace(/^\//, '')
            : parsed.pathname.split(kind === 'skill' ? '/skill/' : kind === 'group' ? '/group/' : '/share/')[1] ?? ''
        );
      } catch {
        kind = url.includes('/group/') ? 'group' : url.includes('/skill/') ? 'skill' : 'bot';
        token = url.split(kind === 'skill' ? '/skill/' : kind === 'group' ? '/group/' : '/share/')[1] ?? '';
      }
      token = token.split(/[?#]/)[0];
      const importKey = `${kind}:${token}`;
      if (!token || importedTokens.current.has(importKey)) return;
      importedTokens.current.add(importKey);
      if (kind === 'group') {
        try {
          const group = await api.joinGroup(token);
          await loadBootstrap();
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
        Alert.alert(
          'Install shared skill?',
          'Skills change how your bots work. Only install skills from people you trust.',
          [
            {
              text: 'Cancel',
              style: 'cancel',
              onPress: () => importedTokens.current.delete(importKey),
            },
            {
              text: 'Install',
              onPress: async () => {
                try {
                  const skill = await api.importSkill(token);
                  await loadBootstrap();
                  Alert.alert('Skill added', `${skill.name} is now in your library.`);
                } catch (value) {
                  importedTokens.current.delete(importKey);
                  Alert.alert('Could not open share', value instanceof Error ? value.message : 'The link may have expired.');
                }
              },
            },
          ],
        );
        return;
      }
      try {
        const bot = await api.importShare(token);
        await loadBootstrap();
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

  const showShareOptions = () => {
    Alert.alert('Share', 'Choose what the link should include.', [
      { text: 'Bot setup', onPress: () => share('bot') },
      { text: 'Conversation', onPress: () => share('chat') },
      { text: 'Cancel', style: 'cancel' },
    ]);
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

  const visibleBots = (data?.bots ?? []).filter((bot) =>
    `${bot.name} ${bot.tagline}`.toLowerCase().includes(search.trim().toLowerCase()),
  );
  const visibleGroups = (data?.groups ?? []).filter((group) =>
    `${group.name} ${group.lastMessage}`.toLowerCase().includes(search.trim().toLowerCase()),
  );
  const drawerSections: { title: string; data: DrawerItem[] }[] = [
    { title: 'Groups', data: visibleGroups.map((value) => ({ kind: 'group' as const, value })) },
    { title: 'FrogBots', data: visibleBots.map((value) => ({ kind: 'bot' as const, value })) },
  ].filter((section) => section.data.length > 0);

  const drawer = (
    <View style={styles.drawer}>
      <View style={[styles.drawerTop, { minHeight: 70 + insets.top, paddingTop: insets.top }]}>
        <View>
          <Text style={styles.appName}>FrogBot</Text>
          <Text style={styles.appTagline}>Your AI team</Text>
        </View>
        <Pressable
          accessibilityLabel="Create bot or group"
          style={({ pressed }) => [styles.addButton, pressed && styles.pressed]}
          onPress={() =>
            Alert.alert('Create new', 'Start a private bot chat or bring people and bots together.', [
              { text: 'New group', onPress: () => setGroupEditor('new') },
              { text: 'New bot', onPress: () => setEditor('new') },
              { text: 'Cancel', style: 'cancel' },
            ])
          }>
          <Text style={styles.addLabel}>+</Text>
        </Pressable>
      </View>
      <TextInput
        value={search}
        onChangeText={setSearch}
        style={styles.search}
        placeholder="Search chats"
        placeholderTextColor="#9B978F"
        autoCorrect={false}
      />
      <SectionList
        sections={drawerSections}
        keyExtractor={(item) => `${item.kind}-${item.value.id}`}
        contentContainerStyle={styles.botList}
        renderSectionHeader={({ section }) => <Text style={styles.sectionLabel}>{section.title}</Text>}
        renderItem={({ item }) => (
          <Pressable
            style={({ pressed }) => [
              styles.botRow,
              selection?.kind === item.kind && selection.id === item.value.id && styles.botRowSelected,
              pressed && styles.pressed,
            ]}
            onPress={() => (item.kind === 'group' ? selectGroup(item.value) : selectBot(item.value))}>
            {item.kind === 'group' ? (
              <GroupAvatar group={item.value} size={42} />
            ) : (
              <BotAvatar color={item.value.color} name={item.value.name} size={42} />
            )}
            <View style={styles.botRowText}>
              <View style={styles.botNameRow}>
                <Text numberOfLines={1} style={styles.botName}>
                  {item.value.name}
                </Text>
                <Text style={styles.botDate}>{friendlyDate(item.value.lastMessageAt)}</Text>
              </View>
              <Text numberOfLines={1} style={styles.botPreview}>
                {item.value.lastMessage}
              </Text>
            </View>
          </Pressable>
        )}
      />
      <View style={[styles.drawerFooter, { paddingBottom: insets.bottom }]}>
        <Pressable
          style={({ pressed }) => [styles.libraryButton, pressed && styles.pressed]}
          onPress={() => {
            setSkillLibraryOpen(true);
            if (!wide) setDrawerOpen(false);
          }}>
          <View style={styles.libraryMark}>
            <Text style={styles.libraryMarkText}>S</Text>
          </View>
          <View style={styles.profileText}>
            <Text style={styles.profileTitle}>Skill library</Text>
            <Text style={styles.profileSubtitle}>Create and share ways of working</Text>
          </View>
          <Text style={styles.libraryChevron}>›</Text>
        </Pressable>
        <View style={styles.drawerBottom}>
          <View style={styles.profileDot} />
          <View style={styles.profileText}>
            <Text style={styles.profileTitle}>{demo ? 'Preview mode' : 'Your account'}</Text>
            <Text style={styles.profileSubtitle}>{demo ? 'Local sample data' : 'Email code sign-in'}</Text>
          </View>
          <Pressable hitSlop={12} onPress={signOut}>
            <Text style={styles.signOut}>Log out</Text>
          </Pressable>
        </View>
      </View>
    </View>
  );

  return (
    <View style={styles.safeArea}>
      <KeyboardAvoidingView style={styles.safeArea} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.shell}>
          {wide && drawerOpen ? <View style={styles.wideDrawer}>{drawer}</View> : null}
          <View style={styles.conversation}>
            <View style={[styles.header, { minHeight: 58 + insets.top, paddingTop: insets.top }]}>
              <Pressable accessibilityLabel="Toggle chat list" hitSlop={12} style={styles.menuButton} onPress={() => setDrawerOpen((value) => !value)}>
                <View style={styles.menuLine} />
                <View style={[styles.menuLine, styles.menuLineShort]} />
              </Pressable>
              {selectedGroup ? (
                <>
                  <GroupAvatar group={selectedGroup} size={34} />
                  <View style={styles.headerIdentity}>
                    <Text numberOfLines={1} style={styles.headerName}>
                      {selectedGroup.name}
                    </Text>
                    <Text numberOfLines={1} style={styles.headerStatus}>
                      {listening
                        ? 'Listening...'
                        : pending
                          ? pendingBotCount > 1
                            ? `${pendingBotCount} FrogBots are working...`
                            : 'A FrogBot is working...'
                          : `${selectedGroup.members.length} people · ${selectedGroup.bots.length} bots`}
                    </Text>
                  </View>
                  <Pressable style={styles.headerAction} hitSlop={10} onPress={() => setGroupEditor('edit')}>
                    <Text style={styles.headerActionLabel}>Details</Text>
                  </Pressable>
                </>
              ) : selectedBot ? (
                <>
                  <BotAvatar color={selectedBot.color} name={selectedBot.name} size={31} />
                  <View style={styles.headerIdentity}>
                    <Text numberOfLines={1} style={styles.headerName}>{selectedBot.name}</Text>
                    <Text numberOfLines={1} style={styles.headerStatus}>
                      {listening ? 'Listening...' : pending ? 'Working...' : 'Ready'}
                    </Text>
                  </View>
                  <Pressable style={styles.headerAction} hitSlop={10} onPress={() => setEditor('edit')}>
                    <Text style={styles.headerActionLabel}>Edit</Text>
                  </Pressable>
                  <Pressable style={styles.moreButton} hitSlop={10} onPress={showShareOptions}>
                    <Text style={styles.moreLabel}>...</Text>
                  </Pressable>
                </>
              ) : null}
            </View>

            {error ? (
              <Pressable style={styles.errorBar} onPress={() => setError('')}>
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

            <View style={[styles.composerWrap, { paddingBottom: 6 + insets.bottom }]}>
              {selectedGroup ? (
                <ScrollView
                  horizontal
                  keyboardShouldPersistTaps="handled"
                  showsHorizontalScrollIndicator={false}
                  contentContainerStyle={styles.replyPicker}>
                  <Pressable
                    style={[styles.replyChip, !activeReplyBotId && styles.replyChipActive]}
                    onPress={() => setReplyBotId(null)}>
                    <PersonAvatar name="People" size={22} />
                    <Text style={[styles.replyChipText, !activeReplyBotId && styles.replyChipTextActive]}>People only</Text>
                  </Pressable>
                  {selectedGroup.bots.length > 1 ? (
                    <Pressable
                      style={[styles.replyChip, activeReplyBotId === ALL_BOTS_REPLY_TARGET && styles.replyChipActive]}
                      onPress={() => setReplyBotId(ALL_BOTS_REPLY_TARGET)}>
                      <GroupAvatar group={selectedGroup} size={22} />
                      <Text style={[styles.replyChipText, activeReplyBotId === ALL_BOTS_REPLY_TARGET && styles.replyChipTextActive]}>Team replies</Text>
                    </Pressable>
                  ) : null}
                  {selectedGroup.bots.map((bot) => {
                    const active = activeReplyBotId === bot.id;
                    return (
                      <Pressable key={bot.id} style={[styles.replyChip, active && styles.replyChipActive]} onPress={() => setReplyBotId(bot.id)}>
                        <BotAvatar name={bot.name} color={bot.color} size={22} />
                        <Text style={[styles.replyChipText, active && styles.replyChipTextActive]}>{bot.name} replies</Text>
                      </Pressable>
                    );
                  })}
                </ScrollView>
              ) : null}
              <View style={styles.composer}>
                <TextInput
                  style={styles.composerInput}
                  value={draft}
                  onChangeText={setDraft}
                  placeholder={listening ? 'Listening...' : selected ? `Message ${selected.name}` : 'Choose a chat'}
                  placeholderTextColor="#9C9991"
                  multiline
                  maxLength={8000}
                  editable={Boolean(selected) && !pending}
                />
                {Platform.OS === 'ios' ? (
                  <Pressable
                    accessibilityLabel={listening ? 'Stop dictation' : 'Dictate message'}
                    style={({ pressed }) => [
                      styles.micButton,
                      listening && styles.micButtonActive,
                      (!selected || pending || sending) && styles.micButtonDisabled,
                      pressed && styles.pressed,
                    ]}
                    disabled={!selected || pending || sending}
                    onPress={toggleDictation}>
                    <MicIcon active={listening} />
                  </Pressable>
                ) : null}
                <Pressable
                  accessibilityLabel="Send message"
                  style={({ pressed }) => [
                    styles.sendButton,
                    (!draft.trim() || pending || sending) && styles.sendDisabled,
                    pressed && styles.pressed,
                  ]}
                  disabled={!draft.trim() || pending || sending}
                  onPress={send}>
                  {sending ? <ActivityIndicator color="white" size="small" /> : <Text style={styles.sendLabel}>↑</Text>}
                </Pressable>
              </View>
              <Text style={styles.composerHint}>Bots can make mistakes. Check important work.</Text>
            </View>
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
    </View>
  );
}

function MessageBubble({ message, groupMode }: { message: Message; groupMode: boolean }) {
  const mine = groupMode && message.authorType === 'user' && message.isMine;
  const assistant = groupMode ? !mine : message.role === 'assistant';
  const botMessage = message.role === 'assistant' || message.authorType === 'bot';
  const activity = message.activity ?? [];
  const avatar = groupMode ? (
    message.authorType === 'bot' ? (
      <BotAvatar name={message.authorName ?? 'FrogBot'} color={message.authorColor ?? '#007A3D'} size={31} />
    ) : (
      <PersonAvatar name={message.authorName ?? 'Person'} size={31} />
    )
  ) : null;
  return (
    <View style={[styles.bubbleRow, assistant ? styles.assistantRow : styles.userRow, groupMode && styles.groupBubbleRow]}>
      {groupMode && !mine ? avatar : null}
      <View style={[styles.bubbleColumn, mine && styles.mineBubbleColumn]}>
        {groupMode ? <Text style={[styles.authorName, mine && styles.authorNameMine]}>{mine ? 'You' : message.authorName}</Text> : null}
        {botMessage ? <AgentActivity active={message.status === 'pending'} steps={activity} /> : null}
        {message.status !== 'pending' ? (
          <View style={[styles.bubble, assistant ? styles.assistantBubble : styles.userBubble, message.status === 'error' && styles.errorBubble]}>
            {botMessage ? (
              <MessageMarkdown>{message.text}</MessageMarkdown>
            ) : (
              <Text style={[styles.messageText, assistant ? styles.assistantText : styles.userText]}>{message.text}</Text>
            )}
          </View>
        ) : null}
      </View>
      {groupMode && mine ? avatar : null}
    </View>
  );
}

function MicIcon({ active }: { active: boolean }) {
  return (
    <View style={styles.micIcon}>
      <View style={[styles.micCapsule, active && styles.micStrokeActive]} />
      <View style={[styles.micCradle, active && styles.micStrokeActive]} />
      <View style={[styles.micStem, active && styles.micFillActive]} />
      <View style={[styles.micFoot, active && styles.micFillActive]} />
    </View>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: '#FBFBF9' },
  shell: { flex: 1, flexDirection: 'row', overflow: 'hidden' },
  wideDrawer: { width: 290 },
  drawer: { flex: 1, backgroundColor: '#F2F1ED', borderRightWidth: StyleSheet.hairlineWidth, borderColor: '#D9D6CF' },
  drawerTop: { minHeight: 70, paddingHorizontal: 17, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  appName: { color: '#007A3D', fontSize: 20, fontWeight: '800', letterSpacing: -0.5 },
  appTagline: { color: '#8B877F', fontSize: 12, marginTop: 1 },
  addButton: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center', backgroundColor: 'white' },
  addLabel: { color: '#22211D', fontSize: 25, fontWeight: '300', marginTop: -2 },
  search: { height: 42, marginHorizontal: 12, borderRadius: 12, backgroundColor: '#E6E4DF', paddingHorizontal: 13, color: '#1F1E1A', fontSize: 14 },
  botList: { padding: 8, paddingTop: 11 },
  sectionLabel: { color: '#8B877F', fontSize: 11, fontWeight: '700', letterSpacing: 0.6, textTransform: 'uppercase', paddingHorizontal: 9, paddingTop: 9, paddingBottom: 5, backgroundColor: '#F2F1ED' },
  botRow: { flexDirection: 'row', alignItems: 'center', gap: 11, minHeight: 64, paddingHorizontal: 9, borderRadius: 13 },
  botRowSelected: { backgroundColor: '#E4F1EA' },
  botRowText: { flex: 1, minWidth: 0 },
  botNameRow: { flexDirection: 'row', alignItems: 'center', gap: 7 },
  botName: { flex: 1, color: '#26251F', fontSize: 15, fontWeight: '600' },
  botDate: { color: '#A09C94', fontSize: 11 },
  botPreview: { color: '#77736B', fontSize: 12, marginTop: 3 },
  drawerFooter: { borderTopWidth: StyleSheet.hairlineWidth, borderColor: '#D9D6CF' },
  libraryButton: { minHeight: 62, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 14, gap: 10 },
  libraryMark: { width: 30, height: 30, borderRadius: 10, backgroundColor: '#E0EDE6', alignItems: 'center', justifyContent: 'center' },
  libraryMarkText: { color: '#007A3D', fontSize: 13, fontWeight: '900' },
  libraryChevron: { color: '#969188', fontSize: 22, marginLeft: 2 },
  drawerBottom: { minHeight: 64, borderTopWidth: StyleSheet.hairlineWidth, borderColor: '#D9D6CF', flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, gap: 10 },
  profileDot: { width: 30, height: 30, borderRadius: 15, backgroundColor: '#007A3D' },
  profileText: { flex: 1 },
  profileTitle: { color: '#282722', fontSize: 13, fontWeight: '600' },
  profileSubtitle: { color: '#8B877F', fontSize: 11, marginTop: 1 },
  signOut: { color: '#6D6961', fontSize: 12, fontWeight: '600' },
  conversation: { flex: 1, backgroundColor: '#FBFBF9' },
  header: { minHeight: 58, paddingHorizontal: 14, flexDirection: 'row', alignItems: 'center', gap: 9, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: '#E0DED8' },
  menuButton: { width: 32, height: 32, justifyContent: 'center', gap: 5 },
  menuLine: { width: 19, height: 2, backgroundColor: '#383731', borderRadius: 2 },
  menuLineShort: { width: 13 },
  headerIdentity: { flex: 1, minWidth: 0 },
  headerName: { color: '#22211E', fontSize: 15, fontWeight: '700' },
  headerStatus: { color: '#007A3D', fontSize: 11, marginTop: 1 },
  headerAction: { paddingHorizontal: 7, paddingVertical: 7 },
  headerActionLabel: { color: '#5B5851', fontSize: 13, fontWeight: '600' },
  moreButton: { width: 32, height: 32, justifyContent: 'center', alignItems: 'center' },
  moreLabel: { color: '#4B4942', fontSize: 19, letterSpacing: 1, marginTop: -7 },
  errorBar: { minHeight: 44, backgroundColor: '#FCECE8', paddingHorizontal: 14, flexDirection: 'row', alignItems: 'center', gap: 10 },
  errorText: { flex: 1, color: '#9E342A', fontSize: 13 },
  errorDismiss: { color: '#9E342A', fontSize: 21 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  messages: { paddingHorizontal: 14, paddingTop: 24, paddingBottom: 18, maxWidth: 780, width: '100%', alignSelf: 'center' },
  emptyMessages: { flexGrow: 1, justifyContent: 'center' },
  emptyState: { alignItems: 'center', paddingHorizontal: 34, marginTop: -30 },
  emptyTitle: { color: '#201F1B', fontSize: 22, fontWeight: '800', letterSpacing: -0.4, marginTop: 18 },
  emptyCopy: { color: '#827E76', fontSize: 14, lineHeight: 20, textAlign: 'center', marginTop: 7, maxWidth: 340 },
  bubbleRow: { flexDirection: 'row', marginBottom: 8 },
  groupBubbleRow: { alignItems: 'flex-end', gap: 7 },
  assistantRow: { justifyContent: 'flex-start' },
  userRow: { justifyContent: 'flex-end' },
  bubbleColumn: { maxWidth: '84%', alignItems: 'flex-start' },
  mineBubbleColumn: { alignItems: 'flex-end' },
  authorName: { color: '#77736B', fontSize: 10, fontWeight: '600', marginBottom: 3, marginHorizontal: 6 },
  authorNameMine: { color: '#007A3D' },
  bubble: { maxWidth: '100%', borderRadius: 18, paddingHorizontal: 14, paddingVertical: 10 },
  assistantBubble: { backgroundColor: '#EFEFEC', borderTopLeftRadius: 6 },
  userBubble: { backgroundColor: '#007A3D', borderBottomRightRadius: 6 },
  errorBubble: { backgroundColor: '#F8E6E1' },
  messageText: { fontSize: 15, lineHeight: 21 },
  assistantText: { color: '#24231F' },
  userText: { color: 'white' },
  composerWrap: { paddingHorizontal: 12, paddingTop: 8, paddingBottom: 6, backgroundColor: '#FBFBF9', alignItems: 'center' },
  replyPicker: { width: '100%', maxWidth: 780, gap: 7, paddingBottom: 7 },
  replyChip: { height: 32, flexDirection: 'row', alignItems: 'center', gap: 6, borderRadius: 16, paddingLeft: 5, paddingRight: 10, borderWidth: 1, borderColor: '#DEDAD2', backgroundColor: 'white' },
  replyChipActive: { borderColor: '#7CAB90', backgroundColor: '#E6F2EB' },
  replyChipText: { color: '#67635C', fontSize: 12, fontWeight: '600' },
  replyChipTextActive: { color: '#006B35' },
  composer: { maxWidth: 780, width: '100%', minHeight: 51, maxHeight: 130, borderRadius: 20, borderWidth: 1, borderColor: '#DCD9D2', backgroundColor: 'white', flexDirection: 'row', alignItems: 'flex-end', paddingLeft: 14, paddingRight: 6, paddingVertical: 6 },
  composerInput: { flex: 1, minHeight: 38, maxHeight: 112, color: '#22211E', fontSize: 15, lineHeight: 20, paddingTop: 9, paddingBottom: 8 },
  micButton: { width: 38, height: 38, borderRadius: 19, alignItems: 'center', justifyContent: 'center', marginRight: 2 },
  micButtonActive: { backgroundColor: '#007A3D' },
  micButtonDisabled: { opacity: 0.4 },
  micIcon: { width: 18, height: 22, alignItems: 'center' },
  micCapsule: { width: 8, height: 12, borderRadius: 5, borderWidth: 1.6, borderColor: '#4F4C45' },
  micCradle: { position: 'absolute', top: 7, width: 15, height: 9, borderLeftWidth: 1.6, borderRightWidth: 1.6, borderBottomWidth: 1.6, borderColor: '#4F4C45', borderBottomLeftRadius: 8, borderBottomRightRadius: 8 },
  micStem: { position: 'absolute', top: 15, width: 1.6, height: 4, backgroundColor: '#4F4C45' },
  micFoot: { position: 'absolute', top: 19, width: 8, height: 1.6, borderRadius: 1, backgroundColor: '#4F4C45' },
  micStrokeActive: { borderColor: 'white' },
  micFillActive: { backgroundColor: 'white' },
  sendButton: { width: 38, height: 38, borderRadius: 19, backgroundColor: '#007A3D', alignItems: 'center', justifyContent: 'center' },
  sendDisabled: { backgroundColor: '#B8D5C6' },
  sendLabel: { color: 'white', fontSize: 22, fontWeight: '700', marginTop: -3 },
  composerHint: { color: '#A19D95', fontSize: 10, marginTop: 5 },
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
