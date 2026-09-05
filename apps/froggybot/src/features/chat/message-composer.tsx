import { ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { BotAvatar } from '@/components/bot-avatar';
import { GroupAvatar, PersonAvatar } from '@/components/participant-avatar';
import type { Attachment, Group } from '@/lib/types';

export const ALL_BOTS_REPLY_TARGET = 'all';

type Props = {
  selectedName?: string;
  group?: Group;
  activeReplyBotId?: string;
  draft: string;
  attachments: Attachment[];
  listening: boolean;
  pending: boolean;
  sending: boolean;
  uploadingAttachment: boolean;
  canAttach: boolean;
  canStop: boolean;
  bottomInset: number;
  onDraftChange: (value: string) => void;
  onAddAttachment: () => void;
  onRemoveAttachment: (fileId: string) => void;
  onReplyTargetChange: (value: string | null) => void;
  onToggleDictation: () => void;
  onSend: () => void;
  onStop: () => void;
};

export function MessageComposer({
  selectedName,
  group,
  activeReplyBotId,
  draft,
  attachments,
  listening,
  pending,
  sending,
  uploadingAttachment,
  canAttach,
  canStop,
  bottomInset,
  onDraftChange,
  onAddAttachment,
  onRemoveAttachment,
  onReplyTargetChange,
  onToggleDictation,
  onSend,
  onStop,
}: Props) {
  const unavailable = !selectedName || pending || sending || uploadingAttachment;
  const cannotSend = (!draft.trim() && attachments.length === 0) || unavailable;
  const replyHint = group
    ? activeReplyBotId === ALL_BOTS_REPLY_TARGET
      ? 'Team replies · one final answer, with a shared file when useful.'
      : activeReplyBotId
        ? `${group.bots.find((bot) => bot.id === activeReplyBotId)?.name ?? 'One FroggyBot'} replies · ask for itineraries, budgets, lists, or PDFs.`
        : 'People only · no FroggyBot will reply.'
    : 'Bots can make mistakes. Check important work.';
  return (
    <View style={[styles.wrap, { paddingBottom: 6 + bottomInset }]}>
      {group ? (
        <ScrollView
          horizontal
          keyboardShouldPersistTaps="handled"
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.replyPicker}>
          <ReplyChip active={!activeReplyBotId} label="People only" onPress={() => onReplyTargetChange(null)}>
            <PersonAvatar name="People" size={24} />
          </ReplyChip>
          {group.bots.length > 1 ? (
            <ReplyChip
              active={activeReplyBotId === ALL_BOTS_REPLY_TARGET}
              label="Team replies"
              onPress={() => onReplyTargetChange(ALL_BOTS_REPLY_TARGET)}>
              <GroupAvatar group={group} size={24} />
            </ReplyChip>
          ) : null}
          {group.bots.map((bot) => (
            <ReplyChip
              key={bot.id}
              active={activeReplyBotId === bot.id}
              label={`${bot.name} replies`}
              onPress={() => onReplyTargetChange(bot.id)}>
              <BotAvatar name={bot.name} color={bot.color} size={24} />
            </ReplyChip>
          ))}
        </ScrollView>
      ) : null}
      {attachments.length || uploadingAttachment ? (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.attachmentList}>
          {attachments.map((file) => (
            <View key={file.id} style={styles.attachmentChip}>
              <Text numberOfLines={1} style={styles.attachmentName}>{file.name}</Text>
              <Text style={styles.attachmentSize}>{Math.max(1, Math.round(file.size / 1000))} KB</Text>
              <Pressable
                accessibilityLabel={`Remove ${file.name}`}
                accessibilityRole="button"
                hitSlop={8}
                onPress={() => onRemoveAttachment(file.id)}>
                <Text style={styles.attachmentRemove}>×</Text>
              </Pressable>
            </View>
          ))}
          {uploadingAttachment ? (
            <View style={styles.uploadingChip}>
              <ActivityIndicator color="#007A3D" size="small" />
              <Text style={styles.uploadingText}>Uploading…</Text>
            </View>
          ) : null}
        </ScrollView>
      ) : null}
      <View style={styles.composer}>
        {canAttach ? (
          <Pressable
            accessibilityLabel="Attach files"
            accessibilityRole="button"
            accessibilityState={{ disabled: unavailable }}
            disabled={unavailable}
            style={({ pressed }) => [styles.attachButton, unavailable && styles.disabled, pressed && styles.pressed]}
            onPress={onAddAttachment}>
            <Text style={styles.attachLabel}>＋</Text>
          </Pressable>
        ) : null}
        <TextInput
          accessibilityLabel={selectedName ? `Message ${selectedName}` : 'Message'}
          style={styles.input}
          value={draft}
          onChangeText={onDraftChange}
          placeholder={listening ? 'Listening...' : selectedName ? `Message ${selectedName}` : 'Choose a chat'}
          placeholderTextColor="#9C9991"
          multiline
          maxLength={8000}
          editable={Boolean(selectedName) && !pending}
        />
        {Platform.OS === 'ios' ? (
          <Pressable
            accessibilityLabel={listening ? 'Stop dictation' : 'Dictate message'}
            accessibilityRole="button"
            accessibilityState={{ disabled: unavailable, selected: listening }}
            style={({ pressed }) => [
              styles.micButton,
              listening && styles.micButtonActive,
              unavailable && styles.disabled,
              pressed && styles.pressed,
            ]}
            disabled={unavailable}
            onPress={onToggleDictation}>
            <MicIcon active={listening} />
          </Pressable>
        ) : null}
        {canStop ? (
          <Pressable
            accessibilityLabel="Stop response"
            accessibilityRole="button"
            style={({ pressed }) => [styles.stopButton, pressed && styles.pressed]}
            onPress={onStop}>
            <View style={styles.stopIcon} />
          </Pressable>
        ) : (
        <Pressable
          accessibilityLabel="Send message"
          accessibilityRole="button"
          accessibilityState={{ disabled: cannotSend, busy: sending || uploadingAttachment }}
          style={({ pressed }) => [
            styles.sendButton,
            cannotSend && styles.sendDisabled,
            pressed && styles.pressed,
          ]}
          disabled={cannotSend}
          onPress={onSend}>
          {sending ? <ActivityIndicator color="white" size="small" /> : <Text style={styles.sendLabel}>↑</Text>}
        </Pressable>
        )}
      </View>
      <Text style={styles.hint}>{replyHint}</Text>
    </View>
  );
}

function ReplyChip({
  active,
  label,
  onPress,
  children,
}: {
  active: boolean;
  label: string;
  onPress: () => void;
  children: React.ReactNode;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
      style={[styles.replyChip, active && styles.replyChipActive]}
      onPress={onPress}>
      {children}
      <Text style={[styles.replyChipText, active && styles.replyChipTextActive]}>{label}</Text>
    </Pressable>
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
  wrap: { paddingHorizontal: 12, paddingTop: 8, backgroundColor: '#FBFBF9', alignItems: 'center' },
  replyPicker: { width: '100%', maxWidth: 780, gap: 7, paddingBottom: 7 },
  replyChip: {
    minHeight: 44,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
    borderRadius: 22,
    paddingLeft: 6,
    paddingRight: 12,
    borderWidth: 1,
    borderColor: '#DEDAD2',
    backgroundColor: 'white',
  },
  replyChipActive: { borderColor: '#7CAB90', backgroundColor: '#E6F2EB' },
  replyChipText: { color: '#67635C', fontSize: 12, fontWeight: '600' },
  replyChipTextActive: { color: '#006B35' },
  attachmentList: { width: '100%', maxWidth: 780, gap: 7, paddingBottom: 7 },
  attachmentChip: {
    maxWidth: 250,
    minHeight: 38,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#D8D4CB',
    backgroundColor: '#F3F2EE',
    paddingLeft: 11,
    paddingRight: 8,
  },
  attachmentName: { maxWidth: 135, color: '#34322D', fontSize: 12, fontWeight: '700' },
  attachmentSize: { color: '#89857D', fontSize: 10 },
  attachmentRemove: { color: '#625E56', fontSize: 20, lineHeight: 22 },
  uploadingChip: { minHeight: 38, flexDirection: 'row', alignItems: 'center', gap: 7, paddingHorizontal: 11 },
  uploadingText: { color: '#657168', fontSize: 12, fontWeight: '600' },
  composer: {
    maxWidth: 780,
    width: '100%',
    minHeight: 51,
    maxHeight: 130,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#DCD9D2',
    backgroundColor: 'white',
    flexDirection: 'row',
    alignItems: 'flex-end',
    paddingLeft: 14,
    paddingRight: 6,
    paddingVertical: 6,
  },
  input: {
    flex: 1,
    minHeight: 38,
    maxHeight: 112,
    color: '#22211E',
    fontSize: 15,
    lineHeight: 20,
    paddingTop: 9,
    paddingBottom: 8,
  },
  attachButton: { width: 34, height: 38, alignItems: 'center', justifyContent: 'center' },
  attachLabel: { color: '#4F4C45', fontSize: 25, fontWeight: '400', marginTop: -2 },
  micButton: { width: 38, height: 38, borderRadius: 19, alignItems: 'center', justifyContent: 'center', marginRight: 2 },
  micButtonActive: { backgroundColor: '#007A3D' },
  disabled: { opacity: 0.4 },
  micIcon: { width: 18, height: 22, alignItems: 'center' },
  micCapsule: { width: 8, height: 12, borderRadius: 5, borderWidth: 1.6, borderColor: '#4F4C45' },
  micCradle: {
    position: 'absolute',
    top: 7,
    width: 15,
    height: 9,
    borderLeftWidth: 1.6,
    borderRightWidth: 1.6,
    borderBottomWidth: 1.6,
    borderColor: '#4F4C45',
    borderBottomLeftRadius: 8,
    borderBottomRightRadius: 8,
  },
  micStem: { position: 'absolute', top: 15, width: 1.6, height: 4, backgroundColor: '#4F4C45' },
  micFoot: { position: 'absolute', top: 19, width: 8, height: 1.6, borderRadius: 1, backgroundColor: '#4F4C45' },
  micStrokeActive: { borderColor: 'white' },
  micFillActive: { backgroundColor: 'white' },
  sendButton: { width: 38, height: 38, borderRadius: 19, backgroundColor: '#007A3D', alignItems: 'center', justifyContent: 'center' },
  sendDisabled: { backgroundColor: '#B8D5C6' },
  sendLabel: { color: 'white', fontSize: 22, fontWeight: '700', marginTop: -3 },
  stopButton: { width: 38, height: 38, borderRadius: 19, backgroundColor: '#E8E5DE', alignItems: 'center', justifyContent: 'center' },
  stopIcon: { width: 12, height: 12, borderRadius: 2, backgroundColor: '#4F4C45' },
  hint: { color: '#A19D95', fontSize: 10, marginTop: 5 },
  pressed: { opacity: 0.7 },
});
