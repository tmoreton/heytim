import { useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  Share,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { BotAvatar } from '@/components/bot-avatar';
import { GroupAvatar, PersonAvatar } from '@/components/participant-avatar';
import type { Bot, Group, GroupDraft, GroupMember } from '@/lib/types';

type Props = {
  group?: Group;
  bots: Bot[];
  onClose: () => void;
  onSave: (draft: GroupDraft) => Promise<void>;
  onShare: () => Promise<string>;
  onRemoveMember: (member: GroupMember) => Promise<void>;
};

export function GroupEditor({ group, bots, onClose, onSave, onShare, onRemoveMember }: Props) {
  const editable = !group || group.isOwner;
  const [name, setName] = useState(group?.name ?? '');
  const [botIds, setBotIds] = useState(group?.bots.map((bot) => bot.id) ?? (bots[0] ? [bots[0].id] : []));
  const [saving, setSaving] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [error, setError] = useState('');
  const displayedBots = editable ? bots : (group?.bots ?? []);

  const save = async () => {
    if (!name.trim()) {
      setError('Give the group a name.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      await onSave({ name: name.trim(), botIds });
      onClose();
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not save this group.');
    } finally {
      setSaving(false);
    }
  };

  const shareInvite = async () => {
    setSharing(true);
    setError('');
    try {
      const url = await onShare();
      await Share.share({ title: `Join ${group?.name ?? name}`, message: `Join my FrogBot group: ${url}`, url });
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not create an invite.');
    } finally {
      setSharing(false);
    }
  };

  const removeMember = (member: GroupMember) => {
    const leaving = !group?.isOwner;
    Alert.alert(leaving ? 'Leave group?' : `Remove ${member.name}?`, leaving ? 'You will need a new invite to rejoin.' : 'They can rejoin with a new invite.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: leaving ? 'Leave' : 'Remove',
        style: 'destructive',
        onPress: async () => {
          try {
            await onRemoveMember(member);
            if (leaving) onClose();
          } catch (value) {
            setError(value instanceof Error ? value.message : 'Could not update the group.');
          }
        },
      },
    ]);
  };

  return (
    <Modal visible animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <KeyboardAvoidingView style={styles.page} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.header}>
          <Pressable hitSlop={12} onPress={onClose}>
            <Text style={styles.headerAction}>{editable ? 'Cancel' : 'Done'}</Text>
          </Pressable>
          <Text style={styles.title}>{group ? 'Group details' : 'New group'}</Text>
          {editable ? (
            <Pressable hitSlop={12} disabled={saving} onPress={save}>
              {saving ? <ActivityIndicator color="#007A3D" /> : <Text style={[styles.headerAction, styles.save]}>Save</Text>}
            </Pressable>
          ) : (
            <View style={styles.headerSpacer} />
          )}
        </View>

        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <View style={styles.identity}>
            {group ? <GroupAvatar group={group} size={62} /> : <View style={styles.newGroupMark}><Text style={styles.newGroupMarkText}>G</Text></View>}
            <View style={styles.identityText}>
              {editable ? (
                <TextInput
                  style={styles.nameInput}
                  value={name}
                  onChangeText={setName}
                  placeholder="Group name"
                  placeholderTextColor="#A4A098"
                  maxLength={64}
                />
              ) : (
                <Text style={styles.groupName}>{name}</Text>
              )}
              <Text style={styles.groupMeta}>
                {group ? `${group.members.length} ${group.members.length === 1 ? 'person' : 'people'} · ${group.bots.length} ${group.bots.length === 1 ? 'bot' : 'bots'}` : 'People join with a private invite link'}
              </Text>
            </View>
          </View>

          {group ? (
            <Pressable style={({ pressed }) => [styles.inviteButton, pressed && styles.pressed]} disabled={sharing} onPress={shareInvite}>
              {sharing ? <ActivityIndicator color="#007A3D" /> : <Text style={styles.inviteText}>Invite people</Text>}
            </Pressable>
          ) : null}

          <Text style={styles.label}>FrogBots</Text>
          <Text style={styles.sectionSubtitle}>Pick the bots people can ask to join the conversation.</Text>
          {displayedBots.map((bot) => {
            const active = botIds.includes(bot.id);
            const availableToEdit = editable;
            return (
              <Pressable
                key={bot.id}
                disabled={!availableToEdit}
                style={[styles.row, active && styles.rowActive]}
                onPress={() => setBotIds((current) => (active ? current.filter((id) => id !== bot.id) : [...current, bot.id]))}>
                <BotAvatar name={bot.name} color={bot.color} size={38} />
                <View style={styles.rowText}>
                  <Text style={styles.rowTitle}>{bot.name}</Text>
                  <Text numberOfLines={1} style={styles.rowSubtitle}>{bot.tagline}</Text>
                </View>
                {availableToEdit ? <View style={[styles.check, active && styles.checkActive]}>{active ? <Text style={styles.checkMark}>✓</Text> : null}</View> : null}
              </Pressable>
            );
          })}

          {group ? (
            <>
              <Text style={[styles.label, styles.peopleLabel]}>People</Text>
              {group.members.map((member) => {
                const canRemove =
                  (group.isOwner && member.role !== 'owner') ||
                  (!group.isOwner && member.id === group.currentUserId);
                return (
                  <View key={member.id} style={styles.row}>
                    <PersonAvatar name={member.name} size={38} />
                    <View style={styles.rowText}>
                      <Text style={styles.rowTitle}>{member.name}</Text>
                      <Text style={styles.rowSubtitle}>{member.role === 'owner' ? 'Group owner' : 'Member'}</Text>
                    </View>
                    {canRemove ? (
                      <Pressable hitSlop={10} onPress={() => removeMember(member)}>
                        <Text style={styles.removeText}>{group.isOwner ? 'Remove' : 'Leave'}</Text>
                      </Pressable>
                    ) : null}
                  </View>
                );
              })}
            </>
          ) : null}
          {error ? <Text style={styles.error}>{error}</Text> : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: '#F8F7F3' },
  header: { minHeight: 58, paddingHorizontal: 18, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: '#DDDAD2', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: '#FBFBF9' },
  title: { fontSize: 16, fontWeight: '700', color: '#171714' },
  headerAction: { color: '#5D5A54', fontSize: 16 },
  save: { color: '#007A3D', fontWeight: '700' },
  headerSpacer: { width: 36 },
  content: { padding: 20, paddingBottom: 60, maxWidth: 680, width: '100%', alignSelf: 'center' },
  identity: { flexDirection: 'row', alignItems: 'center', gap: 16, marginBottom: 22 },
  identityText: { flex: 1, gap: 5 },
  nameInput: { fontSize: 23, fontWeight: '700', color: '#171714', padding: 0 },
  groupName: { fontSize: 23, fontWeight: '700', color: '#171714' },
  groupMeta: { color: '#7B776F', fontSize: 13 },
  newGroupMark: { width: 62, height: 62, borderRadius: 22, backgroundColor: '#DCEDE4', alignItems: 'center', justifyContent: 'center' },
  newGroupMarkText: { color: '#007A3D', fontSize: 24, fontWeight: '900' },
  inviteButton: { height: 48, borderRadius: 15, backgroundColor: '#E1F0E8', alignItems: 'center', justifyContent: 'center', marginBottom: 28 },
  inviteText: { color: '#007A3D', fontSize: 15, fontWeight: '700' },
  label: { fontSize: 14, fontWeight: '700', color: '#24231F', marginBottom: 5 },
  peopleLabel: { marginTop: 27 },
  sectionSubtitle: { color: '#858179', fontSize: 13, marginBottom: 11 },
  row: { minHeight: 62, flexDirection: 'row', gap: 11, alignItems: 'center', paddingHorizontal: 12, paddingVertical: 9, borderRadius: 14, marginBottom: 7, backgroundColor: 'white', borderWidth: 1, borderColor: '#E4E1DA' },
  rowActive: { borderColor: '#8AB99F', backgroundColor: '#EAF5EF' },
  rowText: { flex: 1, minWidth: 0 },
  rowTitle: { color: '#24231F', fontSize: 15, fontWeight: '600' },
  rowSubtitle: { color: '#858179', fontSize: 12, marginTop: 2 },
  check: { width: 22, height: 22, borderRadius: 7, borderWidth: 1, borderColor: '#C9C5BD', alignItems: 'center' },
  checkActive: { backgroundColor: '#007A3D', borderColor: '#007A3D' },
  checkMark: { color: 'white', fontSize: 14, fontWeight: '800' },
  removeText: { color: '#A53A32', fontSize: 12, fontWeight: '600' },
  error: { color: '#B83C32', marginTop: 16 },
  pressed: { opacity: 0.7 },
});
