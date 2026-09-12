import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Linking,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { ActionSheet } from '@/components/action-sheet';
import { PageSheet } from '@/components/page-sheet';
import type { MemoryRecord, MemorySnapshot } from '@froggybot/contracts';

type Props = {
  onClose: () => void;
  onLoad: () => Promise<MemorySnapshot>;
  onCreate?: (kind: 'fact' | 'preference', content: string) => Promise<MemoryRecord>;
  onUpdate: (recordId: string, content: string) => Promise<MemoryRecord>;
  onDelete: (recordId: string) => Promise<void>;
  onExport?: () => Promise<string>;
  title?: string;
  introTitle?: string;
  introCopy?: string;
  editable?: boolean;
  visibleKinds?: MemoryRecord['kind'][];
  creatableKinds?: ('fact' | 'preference')[];
  maxContentLength: number;
};

const sections: { kind: MemoryRecord['kind']; title: string; empty: string }[] = [
  { kind: 'preference', title: 'Preferences', empty: 'No preferences learned yet.' },
  { kind: 'fact', title: 'Facts', empty: 'No facts saved yet.' },
  { kind: 'summary', title: 'Conversation summaries', empty: 'No older conversations have been summarized yet.' },
];
const DEFAULT_VISIBLE_KINDS: MemoryRecord['kind'][] = ['preference', 'fact', 'summary'];
const DEFAULT_CREATABLE_KINDS: ('fact' | 'preference')[] = ['fact', 'preference'];

const learnedDate = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? '' : date.toLocaleDateString();
};

export function MemorySettings({
  onClose,
  onLoad,
  onCreate,
  onUpdate,
  onDelete,
  onExport,
  title = 'Memory',
  introTitle = 'Your memory belongs to you',
  introCopy = 'Review, correct, forget, or download what your bots have learned. Your export is a portable JSON file.',
  editable = true,
  visibleKinds = DEFAULT_VISIBLE_KINDS,
  creatableKinds = DEFAULT_CREATABLE_KINDS,
  maxContentLength,
}: Props) {
  const [snapshot, setSnapshot] = useState<MemorySnapshot>();
  const [editing, setEditing] = useState<MemoryRecord>();
  const [draft, setDraft] = useState('');
  const [pendingDelete, setPendingDelete] = useState<MemoryRecord>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [newKind, setNewKind] = useState<'fact' | 'preference'>(creatableKinds[0] ?? 'fact');
  const [newMemory, setNewMemory] = useState('');

  useEffect(() => {
    let active = true;
    onLoad()
      .then((value) => {
        if (active) setSnapshot(value);
      })
      .catch((value: unknown) => {
        if (active) setError(value instanceof Error ? value.message : 'Could not load memory.');
      });
    return () => {
      active = false;
    };
  }, [onLoad]);

  const startEditing = (record: MemoryRecord) => {
    setEditing(record);
    setDraft(record.content);
    setError('');
  };

  const save = async () => {
    if (!editing || !draft.trim()) return;
    setBusy(true);
    try {
      const updated = await onUpdate(editing.id, draft.trim());
      setSnapshot((current) => current && ({
        ...current,
        records: current.records.map((record) =>
          record.id === editing.id ? { ...record, ...updated } : record),
      }));
      setEditing(undefined);
      setDraft('');
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not update this memory.');
    } finally {
      setBusy(false);
    }
  };

  const forget = async () => {
    if (!pendingDelete) return;
    const recordId = pendingDelete.id;
    setPendingDelete(undefined);
    setBusy(true);
    try {
      await onDelete(recordId);
      setSnapshot((current) => current && ({
        ...current,
        records: current.records.filter((record) => record.id !== recordId),
      }));
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not forget this memory.');
    } finally {
      setBusy(false);
    }
  };

  const download = async () => {
    if (!onExport) return;
    setBusy(true);
    try {
      await Linking.openURL(await onExport());
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not download your memory.');
    } finally {
      setBusy(false);
    }
  };

  const addMemory = async () => {
    if (!onCreate || !newMemory.trim()) return;
    setBusy(true);
    setError('');
    try {
      const created = await onCreate(newKind, newMemory.trim());
      setSnapshot((current) => current && ({
        ...current,
        records: [created, ...current.records],
      }));
      setNewMemory('');
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not add this memory.');
    } finally {
      setBusy(false);
    }
  };

  const visibleSections = sections.filter((section) => visibleKinds.includes(section.kind));

  return (
    <PageSheet accessibilityLabel="Memory settings" onClose={onClose}>
      <KeyboardAvoidingView style={styles.page} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.header}>
          <Text accessibilityRole="header" style={styles.title}>{title}</Text>
          <Pressable accessibilityRole="button" hitSlop={12} onPress={onClose}>
            <Text style={styles.done}>Done</Text>
          </Pressable>
        </View>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <View style={styles.intro}>
            <Text style={styles.introTitle}>{introTitle}</Text>
            <Text style={styles.introCopy}>{introCopy}</Text>
            {onExport ? (
              <Pressable
                accessibilityRole="button"
                disabled={busy || !snapshot}
                style={({ pressed }) => [styles.exportButton, pressed && styles.pressed]}
                onPress={() => void download()}>
                {busy ? <ActivityIndicator size="small" color="#007A3D" /> : <Text style={styles.exportText}>Download my memory</Text>}
              </Pressable>
            ) : null}
          </View>

          <View style={styles.contextCard}>
            <Text style={styles.contextTitle}>How context stays manageable</Text>
            <Text style={styles.contextCopy}>
              Direct chats keep 50 recent turns handy. Group chats keep 40 recent messages. Older context can be recalled from the scoped memories below.
            </Text>
            <Text style={styles.contextCopy}>
              Raw conversation events expire after {snapshot?.rawConversationRetentionDays ?? 30} days. The useful memories below remain until you edit, forget, or delete them.
            </Text>
          </View>

          {editable && onCreate && creatableKinds.length ? (
            <View style={styles.addCard}>
              <Text style={styles.sectionTitle}>Add a memory</Text>
              {creatableKinds.length > 1 ? (
                <View style={styles.kindRow}>
                  {creatableKinds.map((kind) => (
                    <Pressable
                      key={kind}
                      accessibilityRole="button"
                      accessibilityState={{ selected: newKind === kind }}
                      style={[styles.kindButton, newKind === kind && styles.kindButtonActive]}
                      onPress={() => setNewKind(kind)}>
                      <Text style={[styles.kindText, newKind === kind && styles.kindTextActive]}>
                        {kind === 'fact' ? 'Fact' : 'Preference'}
                      </Text>
                    </Pressable>
                  ))}
                </View>
              ) : null}
              <TextInput
                accessibilityLabel="New memory"
                maxLength={maxContentLength}
                multiline
                placeholder="What should the bots remember?"
                placeholderTextColor="#6E6A62"
                style={styles.input}
                value={newMemory}
                onChangeText={setNewMemory}
              />
              <Pressable
                accessibilityRole="button"
                accessibilityState={{ busy, disabled: busy || !newMemory.trim() }}
                disabled={busy || !newMemory.trim()}
                style={({ pressed }) => [styles.addButton, pressed && styles.pressed]}
                onPress={() => void addMemory()}>
                <Text style={styles.addButtonText}>Add memory</Text>
              </Pressable>
            </View>
          ) : null}

          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
          {!snapshot ? <ActivityIndicator color="#007A3D" style={styles.loader} /> : visibleSections.map((section) => {
            const records = snapshot.records.filter((record) => record.kind === section.kind);
            return (
              <View key={section.kind} style={styles.section}>
                <Text style={styles.sectionTitle}>{section.title}</Text>
                {!records.length ? <Text style={styles.empty}>{section.empty}</Text> : records.map((record) => (
                  <View key={record.id} style={styles.record}>
                    {editing?.id === record.id ? (
                      <>
                        <TextInput
                          accessibilityLabel="Memory text"
                          autoFocus
                          maxLength={maxContentLength}
                          multiline
                          style={styles.input}
                          value={draft}
                          onChangeText={setDraft}
                        />
                        <View style={styles.actions}>
                          <Pressable accessibilityRole="button" disabled={busy} hitSlop={8} onPress={() => setEditing(undefined)}>
                            <Text style={styles.cancel}>Cancel</Text>
                          </Pressable>
                          <Pressable accessibilityRole="button" disabled={busy || !draft.trim()} hitSlop={8} onPress={() => void save()}>
                            <Text style={styles.save}>Save</Text>
                          </Pressable>
                        </View>
                      </>
                    ) : (
                      <>
                        <Text style={styles.recordText}>{record.content}</Text>
                        <View style={styles.metaRow}>
                          <Text style={styles.meta}>
                            {[
                              record.scope === 'group' ? 'Shared with this group' : record.botName,
                              record.source === 'manual' ? 'Added manually' : 'Learned from conversation',
                              learnedDate(record.createdAt),
                            ].filter(Boolean).join(' · ')}
                          </Text>
                          {editable ? (
                            <View style={styles.actions}>
                              <Pressable accessibilityRole="button" disabled={busy} hitSlop={8} onPress={() => startEditing(record)}>
                                <Text style={styles.edit}>Edit</Text>
                              </Pressable>
                              <Pressable accessibilityRole="button" disabled={busy} hitSlop={8} onPress={() => setPendingDelete(record)}>
                                <Text style={styles.forget}>Forget</Text>
                              </Pressable>
                            </View>
                          ) : null}
                        </View>
                      </>
                    )}
                  </View>
                ))}
              </View>
            );
          })}
        </ScrollView>
      </KeyboardAvoidingView>
      <ActionSheet
        visible={Boolean(pendingDelete)}
        title="Forget this memory?"
        message="The bots will stop using it. This cannot be undone."
        options={[{ label: 'Forget memory', destructive: true, onPress: () => void forget() }]}
        onClose={() => setPendingDelete(undefined)}
      />
    </PageSheet>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: '#F8F7F3' },
  header: { minHeight: 64, paddingHorizontal: 20, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderBottomWidth: StyleSheet.hairlineWidth, borderColor: '#DEDAD2' },
  title: { color: '#201F1B', fontSize: 22, fontWeight: '800' },
  done: { color: '#007A3D', fontSize: 16, fontWeight: '700' },
  content: { width: '100%', maxWidth: 680, alignSelf: 'center', padding: 20, gap: 16 },
  intro: { borderRadius: 20, backgroundColor: '#E8F3ED', padding: 17 },
  introTitle: { color: '#1E3C2C', fontSize: 18, fontWeight: '800' },
  introCopy: { color: '#4D6758', fontSize: 13, lineHeight: 19, marginTop: 5 },
  exportButton: { minHeight: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 13, backgroundColor: '#FFFFFF', marginTop: 13 },
  exportText: { color: '#007A3D', fontSize: 14, fontWeight: '800' },
  contextCard: { borderRadius: 18, borderWidth: 1, borderColor: '#E2DED6', backgroundColor: '#FFFFFF', padding: 16 },
  contextTitle: { color: '#282722', fontSize: 15, fontWeight: '800' },
  contextCopy: { color: '#77736B', fontSize: 13, lineHeight: 19, marginTop: 7 },
  addCard: { borderRadius: 18, borderWidth: 1, borderColor: '#E2DED6', backgroundColor: '#FFFFFF', padding: 16, gap: 12 },
  kindRow: { flexDirection: 'row', gap: 8 },
  kindButton: { borderRadius: 999, borderWidth: 1, borderColor: '#D5D0C7', paddingHorizontal: 13, paddingVertical: 8 },
  kindButtonActive: { borderColor: '#007A3D', backgroundColor: '#E8F3ED' },
  kindText: { color: '#706C64', fontSize: 13, fontWeight: '700' },
  kindTextActive: { color: '#007A3D' },
  addButton: { minHeight: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 13, backgroundColor: '#007A3D' },
  addButtonText: { color: '#FFFFFF', fontSize: 14, fontWeight: '800' },
  error: { color: '#9E342A', backgroundColor: '#FCECE8', padding: 12, borderRadius: 12, fontSize: 13 },
  loader: { marginVertical: 28 },
  section: { borderRadius: 18, borderWidth: 1, borderColor: '#E2DED6', backgroundColor: '#FFFFFF', padding: 16 },
  sectionTitle: { color: '#282722', fontSize: 16, fontWeight: '800' },
  empty: { color: '#6E6A62', fontSize: 13, marginTop: 12 },
  record: { borderTopWidth: StyleSheet.hairlineWidth, borderColor: '#E2DED6', marginTop: 13, paddingTop: 13 },
  recordText: { color: '#38362F', fontSize: 14, lineHeight: 21 },
  metaRow: { minHeight: 28, flexDirection: 'row', alignItems: 'flex-end', gap: 12, marginTop: 9 },
  meta: { flex: 1, color: '#6E6A62', fontSize: 11 },
  actions: { flexDirection: 'row', alignItems: 'center', gap: 16 },
  edit: { color: '#007A3D', fontSize: 13, fontWeight: '700' },
  forget: { color: '#A53A32', fontSize: 13, fontWeight: '700' },
  input: { minHeight: 112, borderWidth: 1, borderColor: '#CFCAC1', borderRadius: 13, backgroundColor: '#FAFAF7', color: '#292822', fontSize: 14, lineHeight: 20, padding: 11 },
  cancel: { color: '#77736B', fontSize: 14, fontWeight: '700' },
  save: { color: '#007A3D', fontSize: 14, fontWeight: '800' },
  pressed: { opacity: 0.7 },
});
