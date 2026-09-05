import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { AgentActivity } from '@/components/agent-activity';
import { BotAvatar } from '@/components/bot-avatar';
import { MessageMarkdown } from '@/components/message-markdown';
import { PersonAvatar } from '@/components/participant-avatar';
import type { Attachment, Message } from '@/lib/types';

type Props = {
  message: Message;
  groupMode: boolean;
  onApprove?: (message: Message) => Promise<void>;
  onReject?: (message: Message) => Promise<void>;
  onOpenFile?: (file: Attachment) => Promise<void>;
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

export function MessageBubble({ message, groupMode, onApprove, onReject, onOpenFile }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [actingOnApproval, setActingOnApproval] = useState(false);
  const [downloadingFileIds, setDownloadingFileIds] = useState<Set<string>>(() => new Set());
  const [downloadedFileIds, setDownloadedFileIds] = useState<Set<string>>(() => new Set());
  const authorName = message.authorName ?? (message.authorType === 'bot' ? 'FroggyBot' : 'Person');
  const mine = groupMode && message.authorType === 'user' && message.isMine;
  const assistant = groupMode ? !mine : message.role === 'assistant';
  const botMessage = message.role === 'assistant' || message.authorType === 'bot';
  const label = roleLabel(message);
  const queued = message.status === 'waiting';
  const working = message.status === 'pending' || message.status === 'running';
  const awaitingApproval = message.status === 'awaiting_approval';
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

  return (
    <View style={[styles.row, assistant ? styles.assistantRow : styles.userRow, groupMode && styles.groupRow]}>
      {groupMode && !mine ? avatar : null}
      <View style={[styles.column, mine && styles.mineColumn]}>
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
            botColor={message.authorColor}
          />
        ) : null}
        {awaitingApproval ? (
          <View style={[styles.bubble, styles.approvalBubble]}>
            <Text style={styles.approvalTitle}>Approval needed</Text>
            <Text style={styles.approvalCopy}>
              This reply may use {message.approvalTools?.join(', ') || 'an interactive tool'} to act on websites.
              Allow it for this message only?
            </Text>
            <View style={styles.approvalActions}>
              <Pressable
                accessibilityRole="button"
                accessibilityState={{ disabled: actingOnApproval }}
                disabled={actingOnApproval}
                style={({ pressed }) => [styles.rejectButton, pressed && styles.pressed]}
                onPress={() => {
                  if (!onReject) return;
                  setActingOnApproval(true);
                  void onReject(message).finally(() => setActingOnApproval(false));
                }}>
                <Text style={styles.rejectButtonText}>Don’t allow</Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                accessibilityState={{ disabled: actingOnApproval, busy: actingOnApproval }}
                disabled={actingOnApproval}
                style={({ pressed }) => [styles.approveButton, pressed && styles.pressed]}
                onPress={() => {
                  if (!onApprove) return;
                  setActingOnApproval(true);
                  void onApprove(message).finally(() => setActingOnApproval(false));
                }}>
                <Text style={styles.approveButtonText}>{actingOnApproval ? 'Working…' : 'Allow once'}</Text>
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
            {botMessage && compactContribution && !expanded ? (
              <Text numberOfLines={4} style={styles.contributionPreview}>
                {preview}
              </Text>
            ) : botMessage ? (
              <MessageMarkdown>{message.text}</MessageMarkdown>
            ) : (
              <Text style={[styles.message, assistant ? styles.assistantText : styles.userText]}>{message.text}</Text>
            )}
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
  row: { flexDirection: 'row', marginBottom: 8 },
  groupRow: { alignItems: 'flex-end', gap: 7 },
  assistantRow: { justifyContent: 'flex-start' },
  userRow: { justifyContent: 'flex-end' },
  column: { maxWidth: '84%', alignItems: 'flex-start' },
  mineColumn: { alignItems: 'flex-end' },
  author: { color: '#77736B', fontSize: 10, fontWeight: '600', marginBottom: 3, marginHorizontal: 6 },
  mineAuthor: { color: '#007A3D' },
  scheduleLabel: { color: '#61766B', fontSize: 10, fontWeight: '700', marginBottom: 4, marginHorizontal: 6 },
  bubble: { maxWidth: '100%', borderRadius: 18, paddingHorizontal: 14, paddingVertical: 10 },
  assistantBubble: { backgroundColor: '#EFEFEC', borderTopLeftRadius: 6 },
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
  approvalActions: { flexDirection: 'row', gap: 8, marginTop: 12 },
  rejectButton: { borderColor: '#B9A35E', borderRadius: 12, borderWidth: 1, paddingHorizontal: 12, paddingVertical: 8 },
  rejectButtonText: { color: '#5E501F', fontSize: 12, fontWeight: '700' },
  approveButton: { backgroundColor: '#007A3D', borderRadius: 12, paddingHorizontal: 12, paddingVertical: 8 },
  approveButtonText: { color: 'white', fontSize: 12, fontWeight: '800' },
  message: { fontSize: 15, lineHeight: 21 },
  assistantText: { color: '#24231F' },
  userText: { color: 'white' },
  contributionPreview: { color: '#24231F', fontSize: 15, lineHeight: 21 },
  contributionToggle: { alignSelf: 'flex-start', marginTop: 8, paddingVertical: 3 },
  contributionToggleText: { color: '#007A3D', fontSize: 11, fontWeight: '700' },
  pressed: { opacity: 0.65 },
});
