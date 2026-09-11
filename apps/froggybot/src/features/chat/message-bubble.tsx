import * as Clipboard from 'expo-clipboard';
import { useState } from 'react';
import { AccessibilityInfo, Pressable, StyleSheet, Text, View } from 'react-native';

import { AgentActivity } from '@/components/agent-activity';
import { BotAvatar } from '@/components/bot-avatar';
import { MessageMarkdown } from '@/components/message-markdown';
import { PersonAvatar } from '@/components/participant-avatar';
import type { Attachment, Message } from '@/lib/types';

import { isActiveResponse } from './chat-state';
import { MessageAttachment } from './message-attachment';
import { MessageTimingLabel } from './message-timing-label';

type Props = {
  fullWidth: boolean;
  message: Message;
  groupMode: boolean;
  botName?: string;
  botColor?: string;
  onApprove?: (message: Message, always: boolean) => Promise<void>;
  onReject?: (message: Message) => Promise<void>;
  onOpenFile: (file: Attachment) => Promise<void>;
  onResolveFile: (fileId: string) => Promise<string>;
  onOpenLink?: (url: string) => void;
  decisionSaved?: boolean;
  onSaveDecision?: (message: Message) => Promise<void>;
  onActivityExpand?: () => void;
};

const roleLabel = (message: Message) => {
  if (message.roundRole === 'lead') return 'Lead';
  if (message.roundRole === 'contributor') return 'Contribution';
  if (message.roundRole === 'synthesizer') return 'Team answer';
  return undefined;
};

const activityLabel = (message: Message) => {
  if (message.status === 'waiting') {
    return message.roundRole === 'synthesizer'
      ? 'Waiting to combine the team answer'
      : 'Waiting for the previous teammate';
  }
  if (message.roundRole === 'lead') return 'Framing the team’s approach';
  if (message.roundRole === 'contributor') return 'Building on the team';
  if (message.roundRole === 'synthesizer') return 'Combining the team answer';
  return undefined;
};

export function MessageBubble({
  fullWidth,
  message,
  groupMode,
  botName,
  botColor,
  onApprove,
  onReject,
  onOpenFile,
  onResolveFile,
  onOpenLink,
  decisionSaved,
  onSaveDecision,
  onActivityExpand,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const [approvalAction, setApprovalAction] = useState<'reject' | 'once' | 'always'>();
  const [decisionState, setDecisionState] = useState<'idle' | 'saving' | 'saved' | 'error'>(
    decisionSaved ? 'saved' : 'idle',
  );
  const mine = groupMode && message.authorType === 'user' && message.isMine;
  const assistant = groupMode ? !mine : message.role === 'assistant';
  const botMessage = message.role === 'assistant' || message.authorType === 'bot';
  const authorName = message.authorName ?? (botMessage ? botName ?? 'FroggyBot' : 'Person');
  const label = roleLabel(message);
  const queued = message.status === 'waiting';
  const working = isActiveResponse(message);
  const awaitingApproval = message.status === 'awaiting_approval';
  const actingOnApproval = Boolean(approvalAction);
  const compactContribution =
    groupMode &&
    message.status === 'complete' &&
    (message.roundRole === 'lead' || message.roundRole === 'contributor') &&
    message.text.length > 420;
  const preview = compactContribution
    ? message.text.replace(/[#*_`>]/g, '').replace(/\s+/g, ' ').trim()
    : '';
  const avatar = groupMode ? (
    message.authorType === 'bot' ? (
      <BotAvatar name={authorName} color={message.authorColor ?? '#007A3D'} size={31} />
    ) : (
      <PersonAvatar name={authorName} size={31} />
    )
  ) : null;

  const copyMessage = async () => {
    try {
      const copied = await Clipboard.setStringAsync(message.text);
      AccessibilityInfo.announceForAccessibility(
        copied ? 'Message copied to clipboard' : 'Could not copy message',
      );
    } catch {
      AccessibilityInfo.announceForAccessibility('Could not copy message');
    }
  };

  return (
    <View style={[styles.row, assistant ? styles.assistantRow : styles.userRow, groupMode && styles.groupRow]}>
      {groupMode && !mine ? avatar : null}
      <View style={[styles.column, assistant ? styles.assistantColumn : styles.userColumn, fullWidth && styles.mobileColumn]}>
        {groupMode ? (
          <Text style={[styles.author, mine && styles.mineAuthor]}>
            {mine ? 'You' : `${authorName}${label ? ` · ${label}` : ''}`}
          </Text>
        ) : message.source === 'schedule' ? (
          <Text style={styles.scheduleLabel}>Scheduled · {message.scheduleName ?? 'Recurring task'}</Text>
        ) : null}
        {botMessage ? (
          <AgentActivity
            active={working}
            waiting={queued}
            steps={message.activity ?? []}
            label={activityLabel(message)}
            botName={authorName}
            botColor={message.authorColor ?? botColor}
            onExpand={onActivityExpand}
          />
        ) : null}
        {awaitingApproval ? (
          <View style={[styles.bubble, styles.approvalBubble]}>
            <Text style={styles.approvalTitle}>Approval needed</Text>
            <Text style={styles.approvalCopy}>
              This reply may use {message.approvalTools?.join(', ') || 'an interactive tool'} to take action.
              Allow it once, or always allow these tools for this bot in direct chats.
            </Text>
            <View style={styles.approvalActions}>
              <Pressable
                accessibilityRole="button"
                accessibilityState={{ disabled: actingOnApproval }}
                disabled={actingOnApproval}
                style={({ pressed }) => [styles.rejectButton, pressed && styles.pressed]}
                onPress={() => {
                  if (!onReject) return;
                  setApprovalAction('reject');
                  void onReject(message).finally(() => setApprovalAction(undefined));
                }}>
                <Text style={styles.rejectButtonText}>
                  {approvalAction === 'reject' ? 'Working…' : 'Don’t allow'}
                </Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                accessibilityState={{ disabled: actingOnApproval, busy: actingOnApproval }}
                disabled={actingOnApproval}
                style={({ pressed }) => [styles.approveButton, pressed && styles.pressed]}
                onPress={() => {
                  if (!onApprove) return;
                  setApprovalAction('once');
                  void onApprove(message, false).finally(() => setApprovalAction(undefined));
                }}>
                <Text style={styles.approveButtonText}>
                  {approvalAction === 'once' ? 'Working…' : 'Allow once'}
                </Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                accessibilityState={{ disabled: actingOnApproval, busy: actingOnApproval }}
                disabled={actingOnApproval}
                style={({ pressed }) => [styles.alwaysButton, pressed && styles.pressed]}
                onPress={() => {
                  if (!onApprove) return;
                  setApprovalAction('always');
                  void onApprove(message, true).finally(() => setApprovalAction(undefined));
                }}>
                <Text style={styles.alwaysButtonText}>
                  {approvalAction === 'always' ? 'Working…' : 'Always allow'}
                </Text>
              </Pressable>
            </View>
          </View>
        ) : !working && !queued ? (
          <View
            style={[
              styles.bubble,
              assistant ? styles.assistantBubble : styles.userBubble,
              fullWidth && styles.mobileBubble,
              message.roundRole === 'synthesizer' && styles.teamAnswerBubble,
              message.status === 'error' && styles.errorBubble,
            ]}>
            {message.attachments?.map((file) => (
              <MessageAttachment
                key={file.id}
                file={file}
                assistant={assistant}
                onOpenFile={onOpenFile}
                onResolveFile={onResolveFile}
              />
            ))}
            {message.text ? (
              <Pressable
                accessibilityActions={[{ name: 'copy', label: 'Copy message' }]}
                accessibilityHint="Press and hold to copy this message"
                delayLongPress={450}
                onAccessibilityAction={(event) => {
                  if (event.nativeEvent.actionName === 'copy') void copyMessage();
                }}
                onLongPress={() => void copyMessage()}>
                {botMessage && compactContribution && !expanded ? (
                  <Text numberOfLines={4} style={styles.contributionPreview}>
                    {preview}
                  </Text>
                ) : botMessage ? (
                  <MessageMarkdown onOpenLink={onOpenLink}>{message.text}</MessageMarkdown>
                ) : (
                  <Text
                    style={[styles.message, assistant ? styles.assistantText : styles.userText]}>
                    {message.text}
                  </Text>
                )}
              </Pressable>
            ) : null}
            {compactContribution ? (
              <Pressable
                accessibilityRole="button"
                accessibilityState={{ expanded }}
                style={({ pressed }) => [styles.contributionToggle, pressed && styles.pressed]}
                onPress={() => {
                  onActivityExpand?.();
                  setExpanded((value) => !value);
                }}>
                <Text style={styles.contributionToggleText}>
                  {expanded ? 'Hide working note' : 'Show full contribution'}
                </Text>
              </Pressable>
            ) : null}
            {groupMode && message.roundRole === 'synthesizer' && message.status === 'complete' && onSaveDecision ? (
              <Pressable
                accessibilityRole="button"
                accessibilityState={{ busy: decisionState === 'saving', disabled: decisionState === 'saving' || decisionState === 'saved' }}
                disabled={decisionState === 'saving' || decisionState === 'saved'}
                style={styles.decisionButton}
                onPress={() => {
                  setDecisionState('saving');
                  void onSaveDecision(message)
                    .then(() => setDecisionState('saved'))
                    .catch(() => setDecisionState('error'));
                }}>
                <Text style={styles.decisionButtonText}>
                  {decisionState === 'saving'
                    ? 'Saving…'
                    : decisionState === 'saved'
                      ? 'Saved to decisions'
                      : decisionState === 'error'
                        ? 'Try saving decision again'
                        : 'Save decision'}
                </Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}
        <MessageTimingLabel message={message} assistant={assistant} />
      </View>
      {groupMode && mine ? avatar : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { width: '100%', flexDirection: 'row', marginBottom: 8 },
  groupRow: { alignItems: 'flex-end', gap: 7 },
  assistantRow: { justifyContent: 'flex-start' },
  userRow: { justifyContent: 'flex-end' },
  column: { minWidth: 0, flexShrink: 1, alignItems: 'flex-start' },
  assistantColumn: { flex: 1, maxWidth: '100%' },
  userColumn: { width: '84%', maxWidth: 650, alignItems: 'flex-end' },
  mobileColumn: { flex: 1, width: '100%', maxWidth: '100%' },
  author: { color: '#77736B', fontSize: 10, fontWeight: '600', marginBottom: 3, marginHorizontal: 6 },
  mineAuthor: { color: '#007A3D' },
  scheduleLabel: { color: '#61766B', fontSize: 10, fontWeight: '700', marginBottom: 4, marginHorizontal: 6 },
  bubble: { maxWidth: '100%', borderRadius: 18, paddingHorizontal: 14, paddingVertical: 10 },
  assistantBubble: { width: '84%', maxWidth: 650, backgroundColor: '#EFEFEC', borderTopLeftRadius: 6 },
  teamAnswerBubble: { backgroundColor: '#E9F4EE', borderWidth: 1, borderColor: '#A8CFB9' },
  userBubble: { backgroundColor: '#007A3D', borderBottomRightRadius: 6 },
  mobileBubble: { width: '100%', maxWidth: '100%' },
  errorBubble: { backgroundColor: '#F8E6E1' },
  approvalBubble: { backgroundColor: '#FFF7DF', borderColor: '#E7C86A', borderWidth: 1 },
  approvalTitle: { color: '#4B3C0D', fontSize: 14, fontWeight: '800', marginBottom: 5 },
  approvalCopy: { color: '#5E501F', fontSize: 13, lineHeight: 18 },
  approvalActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 12 },
  rejectButton: { borderColor: '#B9A35E', borderRadius: 12, borderWidth: 1, paddingHorizontal: 12, paddingVertical: 8 },
  rejectButtonText: { color: '#5E501F', fontSize: 12, fontWeight: '700' },
  approveButton: { backgroundColor: '#007A3D', borderRadius: 12, paddingHorizontal: 12, paddingVertical: 8 },
  approveButtonText: { color: 'white', fontSize: 12, fontWeight: '800' },
  alwaysButton: { borderColor: '#007A3D', borderRadius: 12, borderWidth: 1, paddingHorizontal: 12, paddingVertical: 8 },
  alwaysButtonText: { color: '#007A3D', fontSize: 12, fontWeight: '800' },
  message: { fontSize: 15, lineHeight: 21 },
  assistantText: { color: '#24231F' },
  userText: { color: 'white' },
  contributionPreview: { color: '#24231F', fontSize: 15, lineHeight: 21 },
  contributionToggle: { alignSelf: 'flex-start', marginTop: 8, paddingVertical: 3 },
  contributionToggleText: { color: '#007A3D', fontSize: 11, fontWeight: '700' },
  decisionButton: { alignSelf: 'flex-start', minHeight: 40, justifyContent: 'center', marginTop: 8, paddingRight: 8 },
  decisionButtonText: { color: '#006B35', fontSize: 12, fontWeight: '800' },
  pressed: { opacity: 0.65 },
});
