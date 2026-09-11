import { memo, useCallback, useLayoutEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { BotAvatar } from '@/components/bot-avatar';
import { GroupAvatar } from '@/components/participant-avatar';
import type { Attachment, Bot, Group, Message } from '@/lib/types';
import type { BrowserApi } from '@/lib/browser-api';
import { BrowserHandoff } from '../browser/browser-handoff';
import { shouldUseBotBrowserForChatLinks } from '../browser/browser-policy';

import { ConversationHeader } from './conversation-header';
import { MessageBubble } from './message-bubble';
import { MessageComposer } from './message-composer';
import { useChatScroll } from './use-chat-scroll';
import { useMessageDictation } from './use-message-dictation';

type Props = {
  browserApi: BrowserApi;
  browserVisible: boolean;
  browserUrl?: string;
  onOpenBrowser: (url?: string) => void;
  onCloseBrowser: () => void;
  onBrowserResumed: () => Promise<void>;
  fullWidth: boolean;
  bot?: Bot;
  group?: Group;
  messages: Message[];
  loading: boolean;
  error: string;
  attachments: Attachment[];
  pending: boolean;
  sending: boolean;
  uploading: boolean;
  canStop: boolean;
  activeBotName?: string;
  waitingBotCount: number;
  activeReplyBotId?: string;
  topInset: number;
  bottomInset: number;
  onError: (message: string) => void;
  onDismissError: () => void;
  onToggleDrawer: () => void;
  onEditGroup: () => void;
  onOpenMenu: () => void;
  onAddAttachment: () => void;
  onRemoveAttachment: (fileId: string) => void;
  onReplyTargetChange: (botId: string | null) => void;
  onSend: (text: string) => Promise<boolean>;
  onStop: () => void;
  onApprove: (message: Message, always: boolean) => Promise<void>;
  onReject: (message: Message) => Promise<void>;
  onOpenFile: (file: Attachment) => Promise<void>;
  onResolveFile: (fileId: string) => Promise<string>;
  onSaveDecision: (message: Message) => Promise<void>;
};

type ChatScroll = ReturnType<typeof useChatScroll>;
type MessageListProps = {
  fullWidth: boolean;
  bot?: Bot;
  group?: Group;
  messages: Message[];
  loading: boolean;
  list: ChatScroll['list'];
  onScroll: ChatScroll['onScroll'];
  onLayout: ChatScroll['onLayout'];
  onContentSizeChange: ChatScroll['onContentSizeChange'];
  onActivityExpand: ChatScroll['preserveScrollPosition'];
  onOpenBrowser: (url?: string) => void;
  onApprove: (message: Message, always: boolean) => Promise<void>;
  onReject: (message: Message) => Promise<void>;
  onOpenFile: (file: Attachment) => Promise<void>;
  onResolveFile: (fileId: string) => Promise<string>;
  onSaveDecision: (message: Message) => Promise<void>;
};

const StableMessageBubble = memo(MessageBubble);
const StableBrowserHandoff = memo(BrowserHandoff);
const messageKey = (message: Message) => message.id;

function useStableCallback<Args extends unknown[], Result>(callback: (...args: Args) => Result) {
  const callbackRef = useRef(callback);
  useLayoutEffect(() => {
    callbackRef.current = callback;
  }, [callback]);
  return useCallback((...args: Args) => callbackRef.current(...args), []);
}

const ConversationMessages = memo(function ConversationMessages({
  fullWidth,
  bot,
  group,
  messages,
  loading,
  list,
  onScroll,
  onLayout,
  onContentSizeChange,
  onActivityExpand,
  onOpenBrowser,
  onApprove,
  onReject,
  onOpenFile,
  onResolveFile,
  onSaveDecision,
}: MessageListProps) {
  if (loading) {
    return (
      <View accessibilityLabel="Loading conversation" accessibilityRole="progressbar" style={styles.center}>
        <ActivityIndicator color={bot?.color ?? '#007A3D'} />
      </View>
    );
  }

  return (
    <FlatList
      ref={list}
      testID="conversation-messages"
      style={styles.messageList}
      data={messages}
      keyExtractor={messageKey}
      contentContainerStyle={[
        styles.messages,
        fullWidth && styles.mobileWidth,
        messages.length === 0 && styles.emptyMessages,
      ]}
      onContentSizeChange={onContentSizeChange}
      onLayout={onLayout}
      onScroll={onScroll}
      scrollEventThrottle={16}
      ListEmptyComponent={
        group ? (
          <View style={styles.emptyState}>
            <GroupAvatar group={group} size={76} />
            <Text style={styles.emptyTitle}>Welcome to {group.name}</Text>
            <Text style={styles.emptyCopy}>Bring people in with one link, keep the group’s memory in one place, and ask a FroggyBot for an itinerary, budget, checklist, or polished PDF.</Text>
          </View>
        ) : bot ? (
          <View style={styles.emptyState}>
            <BotAvatar color={bot.color} name={bot.name} size={70} />
            <Text style={styles.emptyTitle}>Talk to {bot.name}</Text>
            <Text style={styles.emptyCopy}>{bot.tagline || 'Start with the outcome you want.'}</Text>
          </View>
        ) : null
      }
      renderItem={({ item }) => {
        const decisionSaved = group?.decisions.some(
          (decision) => decision.sourceMessageId === item.id,
        );
        return (
          <StableMessageBubble
            fullWidth={fullWidth}
            key={`${item.id}:${decisionSaved ? 'saved' : 'open'}`}
            message={item}
            groupMode={Boolean(group)}
            botName={bot?.name}
            botColor={bot?.color}
            onApprove={bot ? onApprove : undefined}
            onReject={bot ? onReject : undefined}
            onOpenFile={onOpenFile}
            onResolveFile={onResolveFile}
            onOpenLink={shouldUseBotBrowserForChatLinks(bot, Boolean(group)) ? onOpenBrowser : undefined}
            decisionSaved={decisionSaved}
            onSaveDecision={group ? onSaveDecision : undefined}
            onActivityExpand={onActivityExpand}
          />
        );
      }}
    />
  );
});

export function ConversationPanel({
  browserApi,
  browserVisible,
  browserUrl,
  onOpenBrowser,
  onCloseBrowser,
  onBrowserResumed,
  fullWidth,
  bot,
  group,
  messages,
  loading,
  error,
  attachments,
  pending,
  sending,
  uploading,
  canStop,
  activeBotName,
  waitingBotCount,
  activeReplyBotId,
  topInset,
  bottomInset,
  onError,
  onDismissError,
  onToggleDrawer,
  onEditGroup,
  onOpenMenu,
  onAddAttachment,
  onRemoveAttachment,
  onReplyTargetChange,
  onSend,
  onStop,
  onApprove,
  onReject,
  onOpenFile,
  onResolveFile,
  onSaveDecision,
}: Props) {
  const { list, onScroll, onLayout, onContentSizeChange, preserveScrollPosition, jumpToLatest, showJumpToLatest } = useChatScroll();
  const [draft, setDraft] = useState('');
  const stableOnSend = useStableCallback(onSend);
  const stableOpenBrowser = useStableCallback(onOpenBrowser);
  const stableCloseBrowser = useStableCallback(onCloseBrowser);
  const stableBrowserResumed = useStableCallback(onBrowserResumed);
  const stableApprove = useStableCallback(onApprove);
  const stableReject = useStableCallback(onReject);
  const stableOpenFile = useStableCallback(onOpenFile);
  const stableResolveFile = useStableCallback(onResolveFile);
  const stableSaveDecision = useStableCallback(onSaveDecision);
  const { listening, abort: abortDictation, toggle: toggleDictation } = useMessageDictation(
    draft,
    setDraft,
    onError,
    (bot ?? group)?.id ?? '',
  );
  const submitDraft = useCallback(async () => {
    const text = draft.trim();
    abortDictation();
    setDraft('');
    if (!await stableOnSend(text)) setDraft(text);
  }, [abortDictation, draft, stableOnSend]);

  return (
    <View style={styles.conversation}>
      <ConversationHeader
        bot={bot}
        group={group}
        listening={listening}
        pending={pending}
        activeBotName={activeBotName}
        waitingBotCount={waitingBotCount}
        topInset={topInset}
        onToggleDrawer={onToggleDrawer}
        onOpenMenu={onOpenMenu}
      />

      {bot && !group ? (
        <StableBrowserHandoff
          key={bot.id}
          api={browserApi}
          bot={bot}
          active={pending}
          visible={browserVisible}
          initialUrl={browserUrl}
          onClose={stableCloseBrowser}
          onResumed={stableBrowserResumed}
        />
      ) : null}

      {error ? (
        <Pressable
          accessibilityLabel={`${error}. Dismiss`}
          accessibilityRole="alert"
          style={styles.errorBar}
          onPress={onDismissError}>
          <Text numberOfLines={2} style={styles.errorText}>{error}</Text>
          <Text style={styles.errorDismiss}>×</Text>
        </Pressable>
      ) : null}

      {group?.memory ? (
        <Pressable
          accessibilityLabel="Open room context"
          accessibilityRole="button"
          style={({ pressed }) => [styles.memoryBar, pressed && styles.pressed]}
          onPress={onEditGroup}>
          <Text style={styles.memoryLabel}>ROOM CONTEXT</Text>
          <Text numberOfLines={1} style={styles.memoryText}>{group.memory}</Text>
          <Text style={styles.memoryArrow}>›</Text>
        </Pressable>
      ) : null}

      <ConversationMessages
        fullWidth={fullWidth}
        bot={bot}
        group={group}
        messages={messages}
        loading={loading}
        list={list}
        onContentSizeChange={onContentSizeChange}
        onLayout={onLayout}
        onScroll={onScroll}
        onActivityExpand={preserveScrollPosition}
        onOpenBrowser={stableOpenBrowser}
        onApprove={stableApprove}
        onReject={stableReject}
        onOpenFile={stableOpenFile}
        onResolveFile={stableResolveFile}
        onSaveDecision={stableSaveDecision}
      />

      {showJumpToLatest ? (
        <View style={[styles.jumpContainer, fullWidth && styles.mobileWidth]}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Jump to latest message"
            style={styles.jumpButton}
            onPress={jumpToLatest}>
            <Text style={styles.jumpText}>↓ Jump to latest</Text>
          </Pressable>
        </View>
      ) : null}

      <MessageComposer
        fullWidth={fullWidth}
        selectedName={(bot ?? group)?.name}
        group={group}
        activeReplyBotId={activeReplyBotId}
        draft={draft}
        attachments={attachments}
        listening={listening}
        pending={pending}
        sending={sending}
        uploadingAttachment={uploading}
        canAttach={Boolean(bot ?? group)}
        canStop={canStop}
        bottomInset={bottomInset}
        onDraftChange={setDraft}
        onAddAttachment={onAddAttachment}
        onRemoveAttachment={onRemoveAttachment}
        onReplyTargetChange={onReplyTargetChange}
        onToggleDictation={() => void toggleDictation()}
        onSend={() => {
          jumpToLatest();
          void submitDraft();
        }}
        onStop={onStop}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  conversation: { flex: 1, minWidth: 0, backgroundColor: '#FBFBF9' },
  errorBar: { minHeight: 44, backgroundColor: '#FCECE8', paddingHorizontal: 14, flexDirection: 'row', alignItems: 'center', gap: 10 },
  errorText: { flex: 1, color: '#9E342A', fontSize: 13 },
  errorDismiss: { color: '#9E342A', fontSize: 21 },
  memoryBar: { minHeight: 42, flexDirection: 'row', alignItems: 'center', gap: 9, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: '#DCE4DE', backgroundColor: '#F1F7F3', paddingHorizontal: 16 },
  memoryLabel: { color: '#187044', fontSize: 9, fontWeight: '800', letterSpacing: 0.8 },
  memoryText: { flex: 1, color: '#557063', fontSize: 11 },
  memoryArrow: { color: '#5E806E', fontSize: 20, marginTop: -2 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  messageList: { flex: 1, minHeight: 0 },
  messages: { paddingHorizontal: 14, paddingTop: 24, paddingBottom: 42, maxWidth: 780, width: '100%', alignSelf: 'center' },
  mobileWidth: { maxWidth: '100%', paddingHorizontal: 12 },
  jumpContainer: { maxWidth: 780, width: '100%', alignSelf: 'center' },
  jumpButton: { alignSelf: 'flex-end', minHeight: 44, justifyContent: 'center', paddingHorizontal: 16, marginRight: 12 },
  jumpText: { color: '#007A3D', fontSize: 13, fontWeight: '700' },
  emptyMessages: { flexGrow: 1, justifyContent: 'center' },
  emptyState: { alignItems: 'center', paddingHorizontal: 34, marginTop: -30 },
  emptyTitle: { color: '#201F1B', fontSize: 22, fontWeight: '800', letterSpacing: -0.4, marginTop: 18 },
  emptyCopy: { color: '#6E6A62', fontSize: 14, lineHeight: 20, textAlign: 'center', marginTop: 7, maxWidth: 340 },
  pressed: { opacity: 0.72 },
});
