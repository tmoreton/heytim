import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
  TextInput,
  useWindowDimensions,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { BotAvatar } from '@/components/bot-avatar';
import { endSession } from '@/lib/auth';
import { createApi } from '@/lib/api';
import type { Bootstrap, Bot, BotDraft, Message } from '@/lib/types';

import { BotEditor } from './bot-editor';

type Props = {
  demo: boolean;
  onSignedOut: () => void;
};

const friendlyDate = (value: string) => {
  const date = new Date(value);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) return 'Now';
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
};

export function ChatApp({ demo, onSignedOut }: Props) {
  const { width } = useWindowDimensions();
  const wide = width >= 760;
  const api = useMemo(() => createApi(demo), [demo]);
  const list = useRef<FlatList<Message>>(null);
  const importedTokens = useRef(new Set<string>());
  const [data, setData] = useState<Bootstrap>();
  const [selectedId, setSelectedId] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(wide);
  const [search, setSearch] = useState('');
  const [draft, setDraft] = useState('');
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [editor, setEditor] = useState<'new' | 'edit' | undefined>();

  const selected = data?.bots.find((bot) => bot.id === selectedId);
  const pending = messages.some((message) => message.status === 'pending');

  const loadBootstrap = useCallback(async () => {
    try {
      const next = await api.bootstrap();
      setData(next);
      setSelectedId((current) => (next.bots.some((bot) => bot.id === current) ? current : next.bots[0]?.id ?? ''));
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not load your bots.');
    }
  }, [api]);

  const loadMessages = useCallback(async () => {
    if (!selectedId) return;
    try {
      setMessages(await api.messages(selectedId));
      setError('');
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not load this conversation.');
    } finally {
      setLoadingMessages(false);
    }
  }, [api, selectedId]);

  useEffect(() => {
    api
      .bootstrap()
      .then((next) => {
        setData(next);
        setSelectedId((current) => (next.bots.some((bot) => bot.id === current) ? current : next.bots[0]?.id ?? ''));
      })
      .catch((value) => setError(value instanceof Error ? value.message : 'Could not load your bots.'));
  }, [api]);

  useEffect(() => {
    if (!selectedId) return;
    api
      .messages(selectedId)
      .then((next) => {
        setMessages(next);
        setError('');
      })
      .catch((value) => setError(value instanceof Error ? value.message : 'Could not load this conversation.'))
      .finally(() => setLoadingMessages(false));
  }, [api, selectedId]);

  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(loadMessages, 1400);
    return () => clearInterval(timer);
  }, [loadMessages, pending]);

  const importUrl = useCallback(
    async (url: string | null) => {
      if (!url) return;
      let token = '';
      try {
        const parsed = new URL(url);
        token = parsed.hostname === 'share' ? parsed.pathname.replace(/^\//, '') : parsed.pathname.split('/share/')[1] ?? '';
      } catch {
        token = url.split('/share/')[1] ?? '';
      }
      token = token.split(/[?#]/)[0];
      if (!token || importedTokens.current.has(token)) return;
      importedTokens.current.add(token);
      try {
        const bot = await api.importShare(token);
        await loadBootstrap();
        setSelectedId(bot.id);
        Alert.alert('Bot added', `${bot.name} is now on your team.`);
      } catch (value) {
        Alert.alert('Could not open share', value instanceof Error ? value.message : 'The link may have expired.');
      }
    },
    [api, loadBootstrap],
  );

  useEffect(() => {
    Linking.getInitialURL().then(importUrl);
    const subscription = Linking.addEventListener('url', ({ url }) => importUrl(url));
    return () => subscription.remove();
  }, [importUrl]);

  const selectBot = (bot: Bot) => {
    setMessages([]);
    setLoadingMessages(true);
    setSelectedId(bot.id);
    if (!wide) setDrawerOpen(false);
  };

  const saveBot = async (value: BotDraft) => {
    const saved = await api.saveBot(value, editor === 'edit' ? selected?.id : undefined);
    setData((current) => {
      if (!current) return current;
      const exists = current.bots.some((bot) => bot.id === saved.id);
      return { ...current, bots: exists ? current.bots.map((bot) => (bot.id === saved.id ? saved : bot)) : [saved, ...current.bots] };
    });
    setSelectedId(saved.id);
  };

  const send = async () => {
    const text = draft.trim();
    if (!text || !selected || sending || pending) return;
    setSending(true);
    setDraft('');
    try {
      await api.sendMessage(selected, text);
      await loadMessages();
    } catch (value) {
      setDraft(text);
      setError(value instanceof Error ? value.message : 'Could not send that message.');
    } finally {
      setSending(false);
    }
  };

  const share = (scope: 'bot' | 'chat') => {
    if (!selected) return;
    api
      .share(selected.id, scope)
      .then((url) =>
        Share.share({
          title: `Share ${selected.name}`,
          message: scope === 'chat' ? `Open my conversation with ${selected.name}: ${url}` : `Add ${selected.name} to FrogBot: ${url}`,
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

  const signOut = async () => {
    if (!demo) await endSession();
    onSignedOut();
  };

  const visibleBots = (data?.bots ?? []).filter((bot) =>
    `${bot.name} ${bot.tagline}`.toLowerCase().includes(search.trim().toLowerCase()),
  );

  const drawer = (
    <View style={styles.drawer}>
      <View style={styles.drawerTop}>
        <View>
          <Text style={styles.appName}>FrogBot</Text>
          <Text style={styles.appTagline}>Your AI team</Text>
        </View>
        <Pressable style={({ pressed }) => [styles.addButton, pressed && styles.pressed]} onPress={() => setEditor('new')}>
          <Text style={styles.addLabel}>+</Text>
        </Pressable>
      </View>
      <TextInput
        value={search}
        onChangeText={setSearch}
        style={styles.search}
        placeholder="Search bots"
        placeholderTextColor="#9B978F"
        autoCorrect={false}
      />
      <FlatList
        data={visibleBots}
        keyExtractor={(bot) => bot.id}
        contentContainerStyle={styles.botList}
        renderItem={({ item }) => (
          <Pressable
            style={({ pressed }) => [styles.botRow, selectedId === item.id && styles.botRowSelected, pressed && styles.pressed]}
            onPress={() => selectBot(item)}>
            <BotAvatar color={item.color} name={item.name} size={42} />
            <View style={styles.botRowText}>
              <View style={styles.botNameRow}>
                <Text numberOfLines={1} style={styles.botName}>
                  {item.name}
                </Text>
                <Text style={styles.botDate}>{friendlyDate(item.lastMessageAt)}</Text>
              </View>
              <Text numberOfLines={1} style={styles.botPreview}>
                {item.lastMessage}
              </Text>
            </View>
          </Pressable>
        )}
      />
      <View style={styles.drawerBottom}>
        <View style={styles.profileDot} />
        <View style={styles.profileText}>
          <Text style={styles.profileTitle}>{demo ? 'Preview mode' : 'Your account'}</Text>
          <Text style={styles.profileSubtitle}>{demo ? 'Local sample data' : 'Phone code sign-in'}</Text>
        </View>
        <Pressable hitSlop={12} onPress={signOut}>
          <Text style={styles.signOut}>Log out</Text>
        </Pressable>
      </View>
    </View>
  );

  return (
    <SafeAreaView style={styles.safeArea} edges={['top', 'bottom']}>
      <KeyboardAvoidingView style={styles.safeArea} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.shell}>
          {wide && drawerOpen ? <View style={styles.wideDrawer}>{drawer}</View> : null}
          <View style={styles.conversation}>
            <View style={styles.header}>
              <Pressable accessibilityLabel="Toggle bot list" hitSlop={12} style={styles.menuButton} onPress={() => setDrawerOpen((value) => !value)}>
                <View style={styles.menuLine} />
                <View style={[styles.menuLine, styles.menuLineShort]} />
              </Pressable>
              {selected ? (
                <>
                  <BotAvatar color={selected.color} name={selected.name} size={31} />
                  <View style={styles.headerIdentity}>
                    <Text numberOfLines={1} style={styles.headerName}>
                      {selected.name}
                    </Text>
                    <Text numberOfLines={1} style={styles.headerStatus}>
                      {pending ? 'Working...' : 'Ready'}
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
                  selected ? (
                    <View style={styles.emptyState}>
                      <BotAvatar color={selected.color} name={selected.name} size={70} />
                      <Text style={styles.emptyTitle}>Talk to {selected.name}</Text>
                      <Text style={styles.emptyCopy}>{selected.tagline || 'Start with the outcome you want.'}</Text>
                    </View>
                  ) : null
                }
                renderItem={({ item }) => <MessageBubble message={item} />}
              />
            )}

            <View style={styles.composerWrap}>
              <View style={styles.composer}>
                <TextInput
                  style={styles.composerInput}
                  value={draft}
                  onChangeText={setDraft}
                  placeholder={selected ? `Message ${selected.name}` : 'Choose a bot'}
                  placeholderTextColor="#9C9991"
                  multiline
                  maxLength={8000}
                  editable={Boolean(selected) && !pending}
                />
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
          key={`${editor}-${selected?.id ?? 'new'}`}
          bot={editor === 'edit' ? selected : undefined}
          tools={data?.tools ?? []}
          skills={data?.skills ?? []}
          onClose={() => setEditor(undefined)}
          onSave={saveBot}
        />
      ) : null}
    </SafeAreaView>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const assistant = message.role === 'assistant';
  if (message.status === 'pending') {
    return (
      <View style={[styles.bubbleRow, styles.assistantRow]}>
        <View style={[styles.bubble, styles.assistantBubble, styles.typingBubble]}>
          <View style={styles.typingDot} />
          <View style={styles.typingDot} />
          <View style={styles.typingDot} />
        </View>
      </View>
    );
  }
  return (
    <View style={[styles.bubbleRow, assistant ? styles.assistantRow : styles.userRow]}>
      <View style={[styles.bubble, assistant ? styles.assistantBubble : styles.userBubble, message.status === 'error' && styles.errorBubble]}>
        <Text style={[styles.messageText, assistant ? styles.assistantText : styles.userText]}>{message.text}</Text>
      </View>
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
  botRow: { flexDirection: 'row', alignItems: 'center', gap: 11, minHeight: 64, paddingHorizontal: 9, borderRadius: 13 },
  botRowSelected: { backgroundColor: '#E4F1EA' },
  botRowText: { flex: 1, minWidth: 0 },
  botNameRow: { flexDirection: 'row', alignItems: 'center', gap: 7 },
  botName: { flex: 1, color: '#26251F', fontSize: 15, fontWeight: '600' },
  botDate: { color: '#A09C94', fontSize: 11 },
  botPreview: { color: '#77736B', fontSize: 12, marginTop: 3 },
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
  assistantRow: { justifyContent: 'flex-start' },
  userRow: { justifyContent: 'flex-end' },
  bubble: { maxWidth: '84%', borderRadius: 18, paddingHorizontal: 14, paddingVertical: 10 },
  assistantBubble: { backgroundColor: '#EFEFEC', borderTopLeftRadius: 6 },
  userBubble: { backgroundColor: '#007A3D', borderBottomRightRadius: 6 },
  errorBubble: { backgroundColor: '#F8E6E1' },
  messageText: { fontSize: 15, lineHeight: 21 },
  assistantText: { color: '#24231F' },
  userText: { color: 'white' },
  typingBubble: { flexDirection: 'row', gap: 5, paddingHorizontal: 15, paddingVertical: 15 },
  typingDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: '#8E8A82' },
  composerWrap: { paddingHorizontal: 12, paddingTop: 8, paddingBottom: 6, backgroundColor: '#FBFBF9', alignItems: 'center' },
  composer: { maxWidth: 780, width: '100%', minHeight: 51, maxHeight: 130, borderRadius: 20, borderWidth: 1, borderColor: '#DCD9D2', backgroundColor: 'white', flexDirection: 'row', alignItems: 'flex-end', paddingLeft: 14, paddingRight: 6, paddingVertical: 6 },
  composerInput: { flex: 1, minHeight: 38, maxHeight: 112, color: '#22211E', fontSize: 15, lineHeight: 20, paddingTop: 9, paddingBottom: 8 },
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
