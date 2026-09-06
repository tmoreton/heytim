import { useCallback, useRef } from 'react';
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

import { ConversationHeader } from './conversation-header';
import { MessageBubble } from './message-bubble';
import { MessageComposer } from './message-composer';

type Props = {
  bot?: Bot;
  group?: Group;
  messages: Message[];
  loading: boolean;
  error: string;
  draft: string;
  attachments: Attachment[];
  listening: boolean;
  pending: boolean;
  sending: boolean;
  uploading: boolean;
  canStop: boolean;
  activeBotName?: string;
  waitingBotCount: number;
  activeReplyBotId?: string;
  topInset: number;
  bottomInset: number;
  onDismissError: () => void;
  onToggleDrawer: () => void;
  onEditGroup: () => void;
  onOpenBotMenu: () => void;
  onDraftChange: (value: string) => void;
  onAddAttachment: () => void;
  onRemoveAttachment: (fileId: string) => void;
  onReplyTargetChange: (botId: string | null) => void;
  onToggleDictation: () => void;
  onSend: () => void;
  onStop: () => void;
  onApprove: (message: Message, always: boolean) => Promise<void>;
  onReject: (message: Message) => Promise<void>;
  onOpenFile: (file: Attachment) => Promise<void>;
};

export function ConversationPanel({
  bot,
  group,
  messages,
  loading,
  error,
  draft,
  attachments,
  listening,
  pending,
  sending,
  uploading,
  canStop,
  activeBotName,
  waitingBotCount,
  activeReplyBotId,
  topInset,
  bottomInset,
  onDismissError,
  onToggleDrawer,
  onEditGroup,
  onOpenBotMenu,
  onDraftChange,
  onAddAttachment,
  onRemoveAttachment,
  onReplyTargetChange,
  onToggleDictation,
  onSend,
  onStop,
  onApprove,
  onReject,
  onOpenFile,
}: Props) {
  const list = useRef<FlatList<Message>>(null);
  const scrollToLatest = useCallback(() => {
    requestAnimationFrame(() => list.current?.scrollToEnd({ animated: true }));
  }, []);

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
        onEditGroup={onEditGroup}
        onOpenBotMenu={onOpenBotMenu}
      />

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
          accessibilityLabel="Open shared group memory"
          accessibilityRole="button"
          style={({ pressed }) => [styles.memoryBar, pressed && styles.pressed]}
          onPress={onEditGroup}>
          <Text style={styles.memoryLabel}>SHARED MEMORY</Text>
          <Text numberOfLines={1} style={styles.memoryText}>{group.memory}</Text>
          <Text style={styles.memoryArrow}>›</Text>
        </Pressable>
      ) : null}

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={bot?.color ?? '#007A3D'} />
        </View>
      ) : (
        <FlatList
          ref={list}
          data={messages}
          keyExtractor={(message) => message.id}
          contentContainerStyle={[styles.messages, messages.length === 0 && styles.emptyMessages]}
          onContentSizeChange={scrollToLatest}
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
          renderItem={({ item }) => (
            <MessageBubble
              message={item}
              groupMode={Boolean(group)}
              botName={bot?.name}
              botColor={bot?.color}
              onApprove={bot ? onApprove : undefined}
              onReject={bot ? onReject : undefined}
              onOpenFile={onOpenFile}
            />
          )}
        />
      )}

      <MessageComposer
        selectedName={(bot ?? group)?.name}
        group={group}
        activeReplyBotId={activeReplyBotId}
        draft={draft}
        attachments={attachments}
        listening={listening}
        pending={pending}
        sending={sending}
        uploadingAttachment={uploading}
        canAttach={Boolean(bot)}
        canStop={canStop}
        bottomInset={bottomInset}
        onDraftChange={onDraftChange}
        onAddAttachment={onAddAttachment}
        onRemoveAttachment={onRemoveAttachment}
        onReplyTargetChange={onReplyTargetChange}
        onToggleDictation={onToggleDictation}
        onSend={onSend}
        onStop={onStop}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  conversation: { flex: 1, backgroundColor: '#FBFBF9' },
  errorBar: { minHeight: 44, backgroundColor: '#FCECE8', paddingHorizontal: 14, flexDirection: 'row', alignItems: 'center', gap: 10 },
  errorText: { flex: 1, color: '#9E342A', fontSize: 13 },
  errorDismiss: { color: '#9E342A', fontSize: 21 },
  memoryBar: { minHeight: 42, flexDirection: 'row', alignItems: 'center', gap: 9, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: '#DCE4DE', backgroundColor: '#F1F7F3', paddingHorizontal: 16 },
  memoryLabel: { color: '#187044', fontSize: 9, fontWeight: '800', letterSpacing: 0.8 },
  memoryText: { flex: 1, color: '#557063', fontSize: 11 },
  memoryArrow: { color: '#5E806E', fontSize: 20, marginTop: -2 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  messages: { paddingHorizontal: 14, paddingTop: 24, paddingBottom: 42, maxWidth: 780, width: '100%', alignSelf: 'center' },
  emptyMessages: { flexGrow: 1, justifyContent: 'center' },
  emptyState: { alignItems: 'center', paddingHorizontal: 34, marginTop: -30 },
  emptyTitle: { color: '#201F1B', fontSize: 22, fontWeight: '800', letterSpacing: -0.4, marginTop: 18 },
  emptyCopy: { color: '#827E76', fontSize: 14, lineHeight: 20, textAlign: 'center', marginTop: 7, maxWidth: 340 },
  pressed: { opacity: 0.72 },
});
