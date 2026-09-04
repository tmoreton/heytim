import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { AgentActivity } from '@/components/agent-activity';
import { BotAvatar } from '@/components/bot-avatar';
import { MessageMarkdown } from '@/components/message-markdown';
import { PersonAvatar } from '@/components/participant-avatar';
import type { Message } from '@/lib/types';

type Props = {
  message: Message;
  groupMode: boolean;
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

export function MessageBubble({ message, groupMode }: Props) {
  const [expanded, setExpanded] = useState(false);
  const authorName = message.authorName ?? (message.authorType === 'bot' ? 'FrogBot' : 'Person');
  const mine = groupMode && message.authorType === 'user' && message.isMine;
  const assistant = groupMode ? !mine : message.role === 'assistant';
  const botMessage = message.role === 'assistant' || message.authorType === 'bot';
  const label = roleLabel(message);
  const queued = message.status === 'waiting';
  const working = message.status === 'pending';
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
        {!working && !queued ? (
          <View
            style={[
              styles.bubble,
              assistant ? styles.assistantBubble : styles.userBubble,
              message.roundRole === 'synthesizer' && styles.teamAnswerBubble,
              message.status === 'error' && styles.errorBubble,
            ]}>
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
  message: { fontSize: 15, lineHeight: 21 },
  assistantText: { color: '#24231F' },
  userText: { color: 'white' },
  contributionPreview: { color: '#24231F', fontSize: 15, lineHeight: 21 },
  contributionToggle: { alignSelf: 'flex-start', marginTop: 8, paddingVertical: 3 },
  contributionToggleText: { color: '#007A3D', fontSize: 11, fontWeight: '700' },
  pressed: { opacity: 0.65 },
});
