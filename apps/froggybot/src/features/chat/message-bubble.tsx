import * as Clipboard from 'expo-clipboard';
import { useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { AgentActivity } from '@/components/agent-activity';
import { BotAvatar } from '@/components/bot-avatar';
import { MessageMarkdown } from '@/components/message-markdown';
import { PersonAvatar } from '@/components/participant-avatar';
import type { Attachment, Message } from '@/lib/types';

import { isActiveResponse } from './chat-state';

type Props = {
  message: Message;
  groupMode: boolean;
  botName?: string;
  botColor?: string;
  onApprove?: (message: Message, always: boolean) => Promise<void>;
  onReject?: (message: Message) => Promise<void>;
  onOpenFile?: (file: Attachment) => Promise<void>;
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
  message,
  groupMode,
  botName,
  botColor,
  onApprove,
  onReject,
  onOpenFile,
  onActivityExpand,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const [approvalAction, setApprovalAction] = useState<'reject' | 'once' | 'always'>();
  const [downloadingFileIds, setDownloadingFileIds] = useState<Set<string>>(() => new Set());
  const [downloadedFileIds, setDownloadedFileIds] = useState<Set<string>>(() => new Set());
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'error'>('idle');
  const copyFeedbackTimeout = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
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

  useEffect(() => () => {
    if (copyFeedbackTimeout.current) clearTimeout(copyFeedbackTimeout.current);
  }, []);

  const copyMessage = async () => {
    try {
      const copied = await Clipboard.setStringAsync(message.text);
      setCopyState(copied ? 'copied' : 'error');
    } catch {
      setCopyState('error');
    }
    if (copyFeedbackTimeout.current) clearTimeout(copyFeedbackTimeout.current);
    copyFeedbackTimeout.current = setTimeout(() => setCopyState('idle'), 1600);
  };

  return (
    <View style={[styles.row, assistant ? styles.assistantRow : styles.userRow, groupMode && styles.groupRow]}>
      {groupMode && !mine ? avatar : null}
      <View style={[styles.column, assistant ? styles.assistantColumn : styles.userColumn]}>
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
              message.roundRole === 'synthesizer' && styles.teamAnswerBubble,
              message.status === 'error' && styles.errorBubble,
            ]}>
            {message.attachments?.map((file) => {
              const downloading = downloadingFileIds.has(file.id);
              const downloaded = downloadedFileIds.has(file.id);
              const action = downloading ? 'Downloading…' : downloaded ? 'Downloaded' : 'Download';
              return (
                <Pressable
                  key={file.id}
                  accessibilityLabel={`${action} ${file.name}`}
                  accessibilityRole="button"
                  accessibilityState={{ busy: downloading, disabled: downloading }}
                  disabled={downloading}
                  style={({ pressed }) => [
                    styles.fileChip,
                    assistant ? styles.assistantFileChip : styles.userFileChip,
                    pressed && styles.pressed,
                  ]}
                  onPress={() => {
                    if (!onOpenFile) return;
                    setDownloadingFileIds((current) => new Set(current).add(file.id));
                    void onOpenFile(file)
                      .then(() => {
                        setDownloadedFileIds((current) => new Set(current).add(file.id));
                      })
                      .catch(() => undefined)
                      .finally(() => {
                        setDownloadingFileIds((current) => {
                          const next = new Set(current);
                          next.delete(file.id);
                          return next;
                        });
                      });
                  }}>
                  <Text style={[styles.fileIcon, !assistant && styles.userFileText]}>↓</Text>
                  <View style={styles.fileDetails}>
                    <Text numberOfLines={1} style={[styles.fileName, !assistant && styles.userFileText]}>{file.name}</Text>
                    <Text style={[styles.fileSize, !assistant && styles.userFileMeta]}>
                      {Math.max(1, Math.round(file.size / 1000))} KB · {action}
                    </Text>
                  </View>
                </Pressable>
              );
            })}
            {message.text ? (
              <Pressable
                accessibilityHint="Copies this message to the clipboard"
                accessibilityLabel={copyState === 'copied' ? 'Message copied' : 'Copy message'}
                accessibilityRole="button"
                style={({ pressed }) => pressed && styles.copyPressed}
                onPress={() => void copyMessage()}>
                {botMessage && compactContribution && !expanded ? (
                  <Text selectable selectionColor="#79B393" numberOfLines={4} style={styles.contributionPreview}>
                    {preview}
                  </Text>
                ) : botMessage ? (
                  <MessageMarkdown>{message.text}</MessageMarkdown>
                ) : (
                  <Text
                    selectable
                    selectionColor={assistant ? '#79B393' : '#B8E0CB'}
                    style={[styles.message, assistant ? styles.assistantText : styles.userText]}>
                    {message.text}
                  </Text>
                )}
                {copyState !== 'idle' ? (
                  <Text
                    accessibilityLiveRegion="polite"
                    style={[styles.copyFeedback, !assistant && styles.userCopyFeedback]}>
                    {copyState === 'copied' ? 'Copied' : 'Could not copy'}
                  </Text>
                ) : null}
              </Pressable>
            ) : null}
            {compactContribution ? (
              <Pressable
                accessibilityRole="button"
                accessibilityState={{ expanded }}
                style={({ pressed }) => [styles.contributionToggle, pressed && styles.pressed]}
                onPress={() => setExpanded((value) => !value)}>
                <Text style={styles.contributionToggleText}>
                  {expanded ? 'Hide working note' : 'Show full contribution'}
                </Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}
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
  author: { color: '#77736B', fontSize: 10, fontWeight: '600', marginBottom: 3, marginHorizontal: 6 },
  mineAuthor: { color: '#007A3D' },
  scheduleLabel: { color: '#61766B', fontSize: 10, fontWeight: '700', marginBottom: 4, marginHorizontal: 6 },
  bubble: { maxWidth: '100%', borderRadius: 18, paddingHorizontal: 14, paddingVertical: 10 },
  assistantBubble: { width: '84%', maxWidth: 650, backgroundColor: '#EFEFEC', borderTopLeftRadius: 6 },
  teamAnswerBubble: { backgroundColor: '#E9F4EE', borderWidth: 1, borderColor: '#A8CFB9' },
  userBubble: { backgroundColor: '#007A3D', borderBottomRightRadius: 6 },
  errorBubble: { backgroundColor: '#F8E6E1' },
  fileChip: { minWidth: 190, maxWidth: 280, flexDirection: 'row', alignItems: 'center', gap: 8, borderRadius: 11, padding: 8, marginBottom: 8 },
  assistantFileChip: { backgroundColor: '#E1E2DE' },
  userFileChip: { backgroundColor: 'rgba(255,255,255,0.16)' },
  fileIcon: { color: '#007A3D', fontSize: 20, fontWeight: '700' },
  fileDetails: { flex: 1 },
  fileName: { color: '#292823', fontSize: 12, fontWeight: '700' },
  fileSize: { color: '#77736B', fontSize: 10, marginTop: 1 },
  userFileText: { color: 'white' },
  userFileMeta: { color: 'rgba(255,255,255,0.72)' },
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
  copyPressed: { opacity: 0.72 },
  copyFeedback: { alignSelf: 'flex-end', color: '#007A3D', fontSize: 10, fontWeight: '800', marginTop: 5 },
  userCopyFeedback: { color: 'rgba(255,255,255,0.8)' },
  pressed: { opacity: 0.65 },
});
