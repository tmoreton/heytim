import { StyleSheet, Text, View } from 'react-native';

import { AgentActivity } from '@/components/agent-activity';
import { BotAvatar } from '@/components/bot-avatar';
import { MessageMarkdown } from '@/components/message-markdown';
import { PersonAvatar } from '@/components/participant-avatar';
import type { Message } from '@/lib/types';

type Props = {
  message: Message;
  groupMode: boolean;
};

export function MessageBubble({ message, groupMode }: Props) {
  const mine = groupMode && message.authorType === 'user' && message.isMine;
  const assistant = groupMode ? !mine : message.role === 'assistant';
  const botMessage = message.role === 'assistant' || message.authorType === 'bot';
  const avatar = groupMode ? (
    message.authorType === 'bot' ? (
      <BotAvatar name={message.authorName ?? 'FrogBot'} color={message.authorColor ?? '#007A3D'} size={31} />
    ) : (
      <PersonAvatar name={message.authorName ?? 'Person'} size={31} />
    )
  ) : null;

  return (
    <View style={[styles.row, assistant ? styles.assistantRow : styles.userRow, groupMode && styles.groupRow]}>
      {groupMode && !mine ? avatar : null}
      <View style={[styles.column, mine && styles.mineColumn]}>
        {groupMode ? (
          <Text style={[styles.author, mine && styles.mineAuthor]}>{mine ? 'You' : message.authorName}</Text>
        ) : null}
        {botMessage ? <AgentActivity active={message.status === 'pending'} steps={message.activity ?? []} /> : null}
        {message.status !== 'pending' ? (
          <View
            style={[
              styles.bubble,
              assistant ? styles.assistantBubble : styles.userBubble,
              message.status === 'error' && styles.errorBubble,
            ]}>
            {botMessage ? (
              <MessageMarkdown>{message.text}</MessageMarkdown>
            ) : (
              <Text style={[styles.message, assistant ? styles.assistantText : styles.userText]}>{message.text}</Text>
            )}
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
  bubble: { maxWidth: '100%', borderRadius: 18, paddingHorizontal: 14, paddingVertical: 10 },
  assistantBubble: { backgroundColor: '#EFEFEC', borderTopLeftRadius: 6 },
  userBubble: { backgroundColor: '#007A3D', borderBottomRightRadius: 6 },
  errorBubble: { backgroundColor: '#F8E6E1' },
  message: { fontSize: 15, lineHeight: 21 },
  assistantText: { color: '#24231F' },
  userText: { color: 'white' },
});
