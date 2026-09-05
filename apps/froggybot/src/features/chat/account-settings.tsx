import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { ActionSheet } from '@/components/action-sheet';
import type { SharedLink } from '@/lib/types';

type Props = {
  demo: boolean;
  onClose: () => void;
  onOpenMemory: () => void;
  onOpenSkills: () => void;
  onListShares: () => Promise<SharedLink[]>;
  onRevokeShare: (token: string) => Promise<void>;
  onDeleteAccount: () => Promise<void>;
  onSignOut: () => Promise<void>;
};

const kindLabel: Record<SharedLink['kind'], string> = {
  bot: 'Bot setup',
  chat: 'Conversation',
  group: 'Group invite',
  skill: 'Skill',
};

export function AccountSettings({
  demo,
  onClose,
  onOpenMemory,
  onOpenSkills,
  onListShares,
  onRevokeShare,
  onDeleteAccount,
  onSignOut,
}: Props) {
  const [shares, setShares] = useState<SharedLink[]>([]);
  const [loading, setLoading] = useState(!demo);
  const [busyToken, setBusyToken] = useState<string>();
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (demo) return;
    let active = true;
    onListShares()
      .then((items) => {
        if (!active) return;
        setShares(items);
        setError('');
      })
      .catch((value: unknown) => {
        if (active) setError(value instanceof Error ? value.message : 'Could not load shared links.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [demo, onListShares]);

  const revoke = async (share: SharedLink) => {
    setBusyToken(share.token);
    try {
      await onRevokeShare(share.token);
      setShares((current) => current.filter((item) => item.token !== share.token));
      setError('');
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not revoke this link.');
    } finally {
      setBusyToken(undefined);
    }
  };

  const removeAccount = async () => {
    setDeleting(true);
    try {
      await onDeleteAccount();
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not delete your account.');
      setDeleting(false);
    }
  };

  return (
    <Modal visible animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={styles.page}>
        <View style={styles.header}>
          <Text accessibilityRole="header" style={styles.title}>Account</Text>
          <Pressable accessibilityRole="button" hitSlop={12} onPress={onClose}>
            <Text style={styles.done}>Done</Text>
          </Pressable>
        </View>
        <ScrollView contentContainerStyle={styles.content}>
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Manage</Text>
            {!demo ? (
              <Pressable
                accessibilityLabel="Open memory"
                accessibilityRole="button"
                style={({ pressed }) => [styles.settingsRow, pressed && styles.pressed]}
                onPress={onOpenMemory}>
                <View style={styles.memoryMark}>
                  <Text style={styles.memoryMarkText}>M</Text>
                </View>
                <View style={styles.settingsText}>
                  <Text style={styles.settingsTitle}>Memory</Text>
                  <Text style={styles.settingsCopy}>Review, edit, forget, or download what your bots remember</Text>
                </View>
                <Text style={styles.chevron}>›</Text>
              </Pressable>
            ) : null}
            <Pressable
              accessibilityLabel="Open skills and tools"
              accessibilityRole="button"
              style={({ pressed }) => [styles.settingsRow, pressed && styles.pressed]}
              onPress={onOpenSkills}>
              <View style={styles.skillMark}>
                <Text style={styles.skillMarkText}>S</Text>
              </View>
              <View style={styles.settingsText}>
                <Text style={styles.settingsTitle}>Skills & tools</Text>
                <Text style={styles.settingsCopy}>Browse the library and add capabilities to your bots</Text>
              </View>
              <Text style={styles.chevron}>›</Text>
            </Pressable>
          </View>

          {!demo ? (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Active shared links</Text>
              <Text style={styles.sectionCopy}>Revoke links you no longer want people to use.</Text>
              {loading ? (
                <ActivityIndicator color="#007A3D" style={styles.loader} />
              ) : shares.length ? (
                shares.map((share) => (
                  <View key={share.token} style={styles.shareRow}>
                    <View style={styles.shareText}>
                      <Text numberOfLines={1} style={styles.shareTitle}>{share.title}</Text>
                      <Text style={styles.shareMeta}>
                        {kindLabel[share.kind]} · expires {new Date(share.expiresAt * 1000).toLocaleDateString()}
                      </Text>
                    </View>
                    <Pressable
                      accessibilityRole="button"
                      disabled={Boolean(busyToken)}
                      style={({ pressed }) => [styles.revoke, pressed && styles.pressed]}
                      onPress={() => void revoke(share)}>
                      {busyToken === share.token ? <ActivityIndicator size="small" color="#A53A32" /> : <Text style={styles.revokeText}>Revoke</Text>}
                    </Pressable>
                  </View>
                ))
              ) : (
                <Text style={styles.empty}>You do not have any active shared links.</Text>
              )}
            </View>
          ) : null}

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>{demo ? 'Preview mode' : 'Session'}</Text>
            <Pressable style={({ pressed }) => [styles.button, pressed && styles.pressed]} onPress={() => void onSignOut()}>
              <Text style={styles.buttonText}>{demo ? 'Exit preview' : 'Log out'}</Text>
            </Pressable>
          </View>

          {!demo ? (
            <View style={styles.dangerSection}>
              <Text style={styles.sectionTitle}>Delete account</Text>
              <Text style={styles.sectionCopy}>
                Permanently deletes your bots, direct chats, owned groups, schedules, skills, push tokens, invitations, and shared links.
              </Text>
              <Pressable
                accessibilityRole="button"
                disabled={deleting}
                style={({ pressed }) => [styles.deleteButton, pressed && styles.pressed]}
                onPress={() => setConfirmDelete(true)}>
                {deleting ? <ActivityIndicator color="#A53A32" /> : <Text style={styles.deleteText}>Delete my account</Text>}
              </Pressable>
            </View>
          ) : null}
        </ScrollView>
      </View>
      <ActionSheet
        visible={confirmDelete}
        title="Permanently delete your account?"
        message="This cannot be undone. Shared links will stop working and owned groups will be deleted for every member."
        options={[{ label: 'Delete my account', destructive: true, onPress: () => void removeAccount() }]}
        onClose={() => setConfirmDelete(false)}
      />
    </Modal>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: '#F8F7F3' },
  header: { minHeight: 64, paddingHorizontal: 20, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderBottomWidth: StyleSheet.hairlineWidth, borderColor: '#DEDAD2' },
  title: { color: '#201F1B', fontSize: 22, fontWeight: '800' },
  done: { color: '#007A3D', fontSize: 16, fontWeight: '700' },
  content: { width: '100%', maxWidth: 620, alignSelf: 'center', padding: 20, gap: 18 },
  error: { color: '#9E342A', backgroundColor: '#FCECE8', padding: 12, borderRadius: 12, fontSize: 13 },
  section: { backgroundColor: '#FFFFFF', borderRadius: 18, borderWidth: 1, borderColor: '#E2DED6', padding: 16 },
  dangerSection: { backgroundColor: '#FFF9F7', borderRadius: 18, borderWidth: 1, borderColor: '#E8CBC5', padding: 16 },
  sectionTitle: { color: '#282722', fontSize: 16, fontWeight: '800' },
  sectionCopy: { color: '#77736B', fontSize: 13, lineHeight: 19, marginTop: 5, marginBottom: 12 },
  loader: { marginVertical: 18 },
  empty: { color: '#8B877F', fontSize: 13, marginTop: 14 },
  settingsRow: { minHeight: 62, flexDirection: 'row', alignItems: 'center', gap: 11, marginTop: 8 },
  skillMark: { width: 34, height: 34, borderRadius: 11, backgroundColor: '#E0EDE6', alignItems: 'center', justifyContent: 'center' },
  skillMarkText: { color: '#007A3D', fontSize: 14, fontWeight: '900' },
  memoryMark: { width: 34, height: 34, borderRadius: 11, backgroundColor: '#EEE9FA', alignItems: 'center', justifyContent: 'center' },
  memoryMarkText: { color: '#6C5CE7', fontSize: 14, fontWeight: '900' },
  settingsText: { flex: 1, minWidth: 0 },
  settingsTitle: { color: '#282722', fontSize: 14, fontWeight: '700' },
  settingsCopy: { color: '#8B877F', fontSize: 12, marginTop: 3 },
  chevron: { color: '#969188', fontSize: 22 },
  shareRow: { minHeight: 62, flexDirection: 'row', alignItems: 'center', gap: 12, borderTopWidth: StyleSheet.hairlineWidth, borderColor: '#E2DED6', marginTop: 12, paddingTop: 12 },
  shareText: { flex: 1, minWidth: 0 },
  shareTitle: { color: '#282722', fontSize: 14, fontWeight: '700' },
  shareMeta: { color: '#8B877F', fontSize: 12, marginTop: 3 },
  revoke: { minWidth: 68, minHeight: 38, alignItems: 'center', justifyContent: 'center', borderRadius: 11, backgroundColor: '#FCECE8' },
  revokeText: { color: '#A53A32', fontSize: 13, fontWeight: '700' },
  button: { minHeight: 48, marginTop: 12, alignItems: 'center', justifyContent: 'center', borderRadius: 13, backgroundColor: '#E4F1EA' },
  buttonText: { color: '#007A3D', fontSize: 15, fontWeight: '700' },
  deleteButton: { minHeight: 48, alignItems: 'center', justifyContent: 'center', borderRadius: 13, backgroundColor: '#FCECE8' },
  deleteText: { color: '#A53A32', fontSize: 15, fontWeight: '800' },
  pressed: { opacity: 0.7 },
});
