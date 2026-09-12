import { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  Share,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { ActionSheet } from '@/components/action-sheet';
import { BotAvatar } from '@/components/bot-avatar';
import { PageSheet } from '@/components/page-sheet';
import { GroupAvatar, PersonAvatar } from '@/components/participant-avatar';
import { messagePreview } from '@froggybot/client';
import type { AppConstraints, Bot, Group, GroupDraft, GroupMember, MemoryRecord, MemorySnapshot } from '@froggybot/contracts';

import { MemorySettings } from './memory-settings';

type Props = {
  group?: Group;
  constraints: AppConstraints;
  bots: Bot[];
  onClose: () => void;
  onSave: (draft: GroupDraft) => Promise<void>;
  onShare: () => Promise<string>;
  onRemoveMember: (member: GroupMember) => Promise<void>;
  onDelete: () => Promise<void>;
  onDeleteDecision: (decisionId: string) => Promise<void>;
  onLoadMemory: (groupId: string) => Promise<MemorySnapshot>;
  onCreateMemory: (groupId: string, content: string) => Promise<MemoryRecord>;
  onUpdateMemory: (groupId: string, recordId: string, content: string) => Promise<MemoryRecord>;
  onDeleteMemory: (groupId: string, recordId: string) => Promise<void>;
};

export function GroupEditor({
  group,
  constraints,
  bots,
  onClose,
  onSave,
  onShare,
  onRemoveMember,
  onDelete,
  onDeleteDecision,
  onLoadMemory,
  onCreateMemory,
  onUpdateMemory,
  onDeleteMemory,
}: Props) {
  const editable = !group || group.allowedActions?.includes('edit') === true;
  const chief = bots.find((bot) => bot.systemRole === 'chief');
  const [name, setName] = useState(group?.name ?? '');
  const [memory, setMemory] = useState(group?.memory ?? '');
  const [botIds, setBotIds] = useState(() => {
    const startingIds = group?.bots.map((bot) => bot.id) ?? [];
    return editable && chief && !startingIds.includes(chief.id)
      ? [chief.id, ...startingIds]
      : startingIds;
  });
  const [saving, setSaving] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [inviteUrl, setInviteUrl] = useState('');
  const [error, setError] = useState('');
  const [pendingRemoval, setPendingRemoval] = useState<GroupMember>();
  const [deleteConfirmationOpen, setDeleteConfirmationOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [memoryManagerOpen, setMemoryManagerOpen] = useState(false);
  const [deletingDecisionId, setDeletingDecisionId] = useState<string>();
  const displayedBots = editable ? bots : (group?.bots ?? []);

  const save = async () => {
    if (!name.trim()) {
      setError('Give the group a name.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      await onSave({ name: name.trim(), memory: memory.trim(), botIds });
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
      setInviteUrl(url);
      await Share.share({
        title: `Join ${group?.name ?? name} on FroggyBot`,
        message: `You're invited to ${group?.name ?? name} on FroggyBot. One email code opens the shared conversation—no password needed: ${url}`,
        url,
      });
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not create an invite.');
    } finally {
      setSharing(false);
    }
  };

  const removeMember = (member: GroupMember) => {
    setPendingRemoval(member);
  };

  const confirmRemoval = async () => {
    if (!pendingRemoval) return;
    const leaving = pendingRemoval.allowedActions?.includes('leave') === true;
    try {
      await onRemoveMember(pendingRemoval);
      if (leaving) onClose();
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not update the group.');
    }
  };

  const deleteGroup = async () => {
    setDeleting(true);
    setError('');
    try {
      await onDelete();
      onClose();
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not delete this group.');
    } finally {
      setDeleting(false);
    }
  };

  if (group && memoryManagerOpen) {
    return (
      <MemorySettings
        title={`${group.name} memory`}
        introTitle="Memory shared by this group"
        introCopy="Every bot in this group can recall these items. Private memories from members and bot owners are never copied here."
        editable={group.allowedActions?.includes('manageMemory') === true}
        maxContentLength={constraints.memoryMaxLength}
        visibleKinds={['fact', 'preference', 'summary']}
        creatableKinds={['fact']}
        onClose={() => setMemoryManagerOpen(false)}
        onLoad={() => onLoadMemory(group.id)}
        onCreate={(_kind, content) => onCreateMemory(group.id, content)}
        onUpdate={(recordId, content) => onUpdateMemory(group.id, recordId, content)}
        onDelete={(recordId) => onDeleteMemory(group.id, recordId)}
      />
    );
  }

  return (
    <PageSheet accessibilityLabel={group ? `${group.name} room context` : 'Create a group'} onClose={onClose}>
      <KeyboardAvoidingView style={styles.page} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.header}>
          <Pressable accessibilityRole="button" hitSlop={12} onPress={onClose}>
            <Text style={styles.headerAction}>{editable ? 'Cancel' : 'Done'}</Text>
          </Pressable>
          <Text style={styles.title}>{group ? 'Room context' : 'New group'}</Text>
          {editable ? (
            <Pressable accessibilityRole="button" accessibilityState={{ busy: saving, disabled: saving }} hitSlop={12} disabled={saving} onPress={save}>
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
                  accessibilityLabel="Group name"
                  style={styles.nameInput}
                  value={name}
                  onChangeText={setName}
                  placeholder="Group name"
                  placeholderTextColor="#6E6A62"
                  maxLength={constraints.groupNameMaxLength}
                />
              ) : (
                <Text style={styles.groupName}>{name}</Text>
              )}
              <Text style={styles.groupMeta}>
                {group ? `${group.members.length} ${group.members.length === 1 ? 'person' : 'people'} · ${group.bots.length} ${group.bots.length === 1 ? 'bot' : 'bots'}` : 'People join with a private invite link'}
              </Text>
            </View>
          </View>

          {group?.allowedActions?.includes('share') ? (
            <View style={styles.inviteCard}>
              <View style={styles.inviteCardTop}>
                <View style={styles.inviteIcon}>
                  <GroupAvatar group={group} size={42} />
                </View>
                <View style={styles.inviteCardCopy}>
                  <Text style={styles.inviteCardTitle}>Bring someone into the group</Text>
                  <Text style={styles.inviteCardSubtitle}>One email code opens this group—no password or setup maze.</Text>
                </View>
              </View>
              {inviteUrl ? <Text numberOfLines={1} style={styles.inviteUrl}>froggybot.com/invite</Text> : null}
              <Pressable
                accessibilityRole="button"
                accessibilityState={{ busy: sharing, disabled: sharing }}
                style={({ pressed }) => [styles.inviteButton, pressed && styles.pressed]}
                disabled={sharing}
                onPress={shareInvite}>
                {sharing ? <ActivityIndicator color="white" /> : <Text style={styles.inviteText}>{inviteUrl ? 'Share again' : 'Share invitation'}</Text>}
              </Pressable>
            </View>
          ) : null}

          <View style={styles.memoryCard}>
            <Text style={styles.memoryTitle}>Pinned facts</Text>
            <Text style={styles.memorySubtitle}>
              Goals, constraints, and accepted decisions shown to every specialist. Everyone can see them; the owner can edit them.
            </Text>
            {editable ? (
              <TextInput
                accessibilityLabel="Pinned room facts"
                multiline
                maxLength={constraints.groupMemoryMaxLength}
                placeholder="Example: We are planning a four-day trip in October. Keep the total under $1,200 per person and always include vegetarian options."
                placeholderTextColor="#6E6A62"
                style={styles.memoryInput}
                textAlignVertical="top"
                value={memory}
                onChangeText={setMemory}
              />
            ) : (
              <Text style={[styles.memoryValue, !memory && styles.memoryEmpty]}>
                {memory || 'The owner has not pinned any room facts yet.'}
              </Text>
            )}
            {editable ? (
              <Text style={styles.memoryCount}>
                {memory.length.toLocaleString()} / {constraints.groupMemoryMaxLength.toLocaleString()}
              </Text>
            ) : null}
            {group?.memoryUpdatedAt ? (
              <Text style={styles.memoryMeta}>
                Updated by {group.memoryUpdatedByName ?? 'the group owner'} · {new Date(group.memoryUpdatedAt).toLocaleDateString()}
              </Text>
            ) : null}
            {group?.allowedActions?.includes('viewMemory') || group?.allowedActions?.includes('manageMemory') ? (
              <Pressable
                accessibilityRole="button"
                style={({ pressed }) => [styles.memoryManageButton, pressed && styles.pressed]}
                onPress={() => setMemoryManagerOpen(true)}>
                <Text style={styles.memoryManageText}>
                  {group.allowedActions?.includes('manageMemory') ? 'Manage what FroggyBot learned' : 'View what FroggyBot learned'}
                </Text>
              </Pressable>
            ) : null}
          </View>

          {group ? (
            <View style={styles.decisionCard}>
              <Text style={styles.memoryTitle}>Decisions</Text>
              <Text style={styles.memorySubtitle}>Accepted team answers saved by people in this room.</Text>
              {group.decisions.length ? group.decisions.map((decision) => (
                <View key={decision.id} style={styles.decisionRow}>
                  <View style={styles.rowText}>
                    <Text style={styles.decisionText}>{messagePreview(decision.text, 220)}</Text>
                    <Text style={styles.memoryMeta}>
                      From {decision.sourceAuthorName} · saved by {decision.createdByName} · {new Date(decision.createdAt).toLocaleDateString()}
                    </Text>
                  </View>
                  {decision.allowedActions?.includes('remove') ? (
                    <Pressable
                      accessibilityLabel={`Remove decision saved by ${decision.createdByName}`}
                      accessibilityRole="button"
                      disabled={deletingDecisionId === decision.id}
                      onPress={() => {
                        setDeletingDecisionId(decision.id);
                        void onDeleteDecision(decision.id)
                          .catch((value) => setError(value instanceof Error ? value.message : 'Could not remove the decision.'))
                          .finally(() => setDeletingDecisionId(undefined));
                      }}>
                      <Text style={styles.removeText}>{deletingDecisionId === decision.id ? 'Removing…' : 'Remove'}</Text>
                    </Pressable>
                  ) : null}
                </View>
              )) : <Text style={styles.memoryEmpty}>Save a final team answer to keep the decision here.</Text>}
            </View>
          ) : null}

          <Text style={styles.label}>Specialists</Text>
          <Text style={styles.sectionSubtitle}>Choose the FroggyBots people can bring into this room. Files attached to messages stay scoped to current room members.</Text>
          {displayedBots.map((bot) => {
            const active = botIds.includes(bot.id);
            const availableToEdit = editable && bot.systemRole !== 'chief';
            return (
              <Pressable
                key={bot.id}
                accessibilityRole="checkbox"
                accessibilityState={{ checked: active, disabled: !availableToEdit }}
                aria-checked={active}
                disabled={!availableToEdit}
                style={[styles.row, active && styles.rowActive]}
                onPress={() => setBotIds((current) => (active ? current.filter((id) => id !== bot.id) : [...current, bot.id]))}>
                <BotAvatar name={bot.name} color={bot.color} size={38} />
                <View style={styles.rowText}>
                  <Text style={styles.rowTitle}>{bot.name}</Text>
                  <Text numberOfLines={1} style={styles.rowSubtitle}>
                    {bot.systemRole === 'chief' ? `${bot.tagline} Always included.` : bot.tagline}
                  </Text>
                </View>
                {availableToEdit ? <View style={[styles.check, active && styles.checkActive]}>{active ? <Text style={styles.checkMark}>✓</Text> : null}</View> : null}
              </Pressable>
            );
          })}

          {group ? (
            <>
              <Text style={[styles.label, styles.peopleLabel]}>People</Text>
              {group.members.map((member) => {
                const canRemove = member.allowedActions?.some((action) => action === 'remove' || action === 'leave');
                return (
                  <View key={member.id} style={styles.row}>
                    <PersonAvatar name={member.name} size={38} />
                    <View style={styles.rowText}>
                      <Text style={styles.rowTitle}>{member.name}</Text>
                      <Text style={styles.rowSubtitle}>{member.role === 'owner' ? 'Group owner' : 'Member'}</Text>
                    </View>
                    {canRemove ? (
                      <Pressable accessibilityRole="button" hitSlop={10} onPress={() => removeMember(member)}>
                        <Text style={styles.removeText}>{member.allowedActions?.includes('leave') ? 'Leave' : 'Remove'}</Text>
                      </Pressable>
                    ) : null}
                  </View>
                );
              })}
            </>
          ) : null}
          {group?.allowedActions?.includes('delete') ? (
            <View style={styles.dangerZone}>
              <Text style={styles.dangerTitle}>Delete group</Text>
              <Text style={styles.dangerCopy}>Permanently delete this group and its chat for everyone.</Text>
              <Pressable
                accessibilityRole="button"
                accessibilityState={{ busy: deleting, disabled: deleting }}
                disabled={deleting}
                style={({ pressed }) => [styles.deleteButton, pressed && styles.pressed]}
                onPress={() => setDeleteConfirmationOpen(true)}>
                {deleting ? <ActivityIndicator color="#A53A32" /> : <Text style={styles.deleteText}>Delete group</Text>}
              </Pressable>
            </View>
          ) : null}
          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
        </ScrollView>
      </KeyboardAvoidingView>
      <ActionSheet
        visible={Boolean(pendingRemoval)}
        title={pendingRemoval?.allowedActions?.includes('remove') ? `Remove ${pendingRemoval.name}?` : 'Leave group?'}
        message={pendingRemoval?.allowedActions?.includes('remove') ? 'They can rejoin with a new invite.' : 'You will need a new invite to rejoin.'}
        options={[
          {
            label: pendingRemoval?.allowedActions?.includes('remove') ? 'Remove' : 'Leave',
            destructive: true,
            onPress: confirmRemoval,
          },
        ]}
        onClose={() => setPendingRemoval(undefined)}
      />
      <ActionSheet
        visible={deleteConfirmationOpen}
        title={`Delete ${group?.name ?? 'this group'}?`}
        message="This permanently deletes the group and its full conversation for every member."
        options={[{ label: 'Delete group', destructive: true, onPress: deleteGroup }]}
        onClose={() => setDeleteConfirmationOpen(false)}
      />
    </PageSheet>
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
  groupMeta: { color: '#6E6A62', fontSize: 13 },
  newGroupMark: { width: 62, height: 62, borderRadius: 22, backgroundColor: '#DCEDE4', alignItems: 'center', justifyContent: 'center' },
  newGroupMarkText: { color: '#007A3D', fontSize: 24, fontWeight: '900' },
  inviteCard: { backgroundColor: '#EAF5EF', borderWidth: 1, borderColor: '#C9E2D4', borderRadius: 20, padding: 15, marginBottom: 28 },
  inviteCardTop: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  inviteIcon: { width: 50, height: 50, borderRadius: 16, backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center' },
  inviteCardCopy: { flex: 1, minWidth: 0 },
  inviteCardTitle: { color: '#163E2A', fontSize: 15, fontWeight: '700' },
  inviteCardSubtitle: { color: '#5F7D6C', fontSize: 12, lineHeight: 17, marginTop: 3 },
  inviteUrl: { color: '#58806A', fontSize: 11, fontWeight: '600', marginTop: 13 },
  inviteButton: { height: 48, borderRadius: 15, backgroundColor: '#007A3D', alignItems: 'center', justifyContent: 'center', marginTop: 12 },
  inviteText: { color: '#FFFFFF', fontSize: 15, fontWeight: '700' },
  memoryCard: { borderWidth: 1, borderColor: '#D8D4CB', borderRadius: 20, backgroundColor: '#FFFFFF', padding: 15, marginBottom: 28 },
  memoryTitle: { color: '#272620', fontSize: 15, fontWeight: '700' },
  memorySubtitle: { color: '#77736B', fontSize: 12, lineHeight: 18, marginTop: 4 },
  memoryInput: { minHeight: 128, borderWidth: 1, borderColor: '#DEDAD1', borderRadius: 14, backgroundColor: '#FAFAF7', color: '#292822', fontSize: 14, lineHeight: 20, paddingHorizontal: 12, paddingVertical: 11, marginTop: 12 },
  memoryValue: { color: '#35332D', fontSize: 14, lineHeight: 21, marginTop: 12 },
  memoryEmpty: { color: '#6E6A62', fontStyle: 'italic' },
  memoryCount: { alignSelf: 'flex-end', color: '#6E6A62', fontSize: 10, marginTop: 6 },
  memoryMeta: { color: '#6E6A62', fontSize: 11, marginTop: 8 },
  memoryManageButton: { minHeight: 42, alignItems: 'center', justifyContent: 'center', borderRadius: 12, backgroundColor: '#E8F3ED', marginTop: 12 },
  memoryManageText: { color: '#007A3D', fontSize: 13, fontWeight: '700' },
  decisionCard: { borderWidth: 1, borderColor: '#C9E2D4', borderRadius: 20, backgroundColor: '#F4FAF6', padding: 15, marginBottom: 28 },
  decisionRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingTop: 12, marginTop: 10, borderTopWidth: 1, borderColor: '#D7E7DC' },
  decisionText: { color: '#2C342F', fontSize: 13, lineHeight: 19, fontWeight: '600' },
  label: { fontSize: 14, fontWeight: '700', color: '#24231F', marginBottom: 5 },
  peopleLabel: { marginTop: 27 },
  sectionSubtitle: { color: '#6E6A62', fontSize: 13, marginBottom: 11 },
  row: { minHeight: 62, flexDirection: 'row', gap: 11, alignItems: 'center', paddingHorizontal: 12, paddingVertical: 9, borderRadius: 14, marginBottom: 7, backgroundColor: 'white', borderWidth: 1, borderColor: '#E4E1DA' },
  rowActive: { borderColor: '#8AB99F', backgroundColor: '#EAF5EF' },
  rowText: { flex: 1, minWidth: 0 },
  rowTitle: { color: '#24231F', fontSize: 15, fontWeight: '600' },
  rowSubtitle: { color: '#6E6A62', fontSize: 12, marginTop: 2 },
  check: { width: 22, height: 22, borderRadius: 7, borderWidth: 1, borderColor: '#C9C5BD', alignItems: 'center' },
  checkActive: { backgroundColor: '#007A3D', borderColor: '#007A3D' },
  checkMark: { color: 'white', fontSize: 14, fontWeight: '800' },
  removeText: { color: '#A53A32', fontSize: 12, fontWeight: '600' },
  dangerZone: { marginTop: 30, paddingTop: 22, borderTopWidth: 1, borderColor: '#DDDAD2' },
  dangerTitle: { color: '#52251F', fontSize: 14, fontWeight: '700' },
  dangerCopy: { color: '#8C6A64', fontSize: 13, lineHeight: 19, marginTop: 5 },
  deleteButton: { minHeight: 48, borderRadius: 14, borderWidth: 1, borderColor: '#E2B8B1', alignItems: 'center', justifyContent: 'center', marginTop: 13, backgroundColor: '#FFF8F6' },
  deleteText: { color: '#A53A32', fontSize: 15, fontWeight: '700' },
  error: { color: '#B83C32', marginTop: 16 },
  pressed: { opacity: 0.7 },
});
