import { useState } from 'react';
import {
  ActivityIndicator,
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

import type { Capability, Skill, SkillDetail, SkillDraft } from '@/lib/types';

const emptyDraft: SkillDraft = {
  name: '',
  description: '',
  instructions: '',
  requiredToolIds: [],
  visibility: 'private',
};

type Props = {
  skills: Skill[];
  tools: Capability[];
  onClose: () => void;
  onLoad: (skillId: string) => Promise<SkillDetail>;
  onSave: (draft: SkillDraft, skillId?: string) => Promise<SkillDetail>;
  onShare: (skillId: string) => Promise<string>;
  onChanged: () => Promise<void>;
};

export function SkillLibrary({ skills, tools, onClose, onLoad, onSave, onShare, onChanged }: Props) {
  const [selected, setSelected] = useState<SkillDetail>();
  const [draft, setDraft] = useState<SkillDraft>(emptyDraft);
  const [mode, setMode] = useState<'list' | 'view' | 'edit' | 'new'>('list');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const open = async (skill: Skill) => {
    setSelected({ ...skill, instructions: '' });
    setError('');
    setMode('view');
    setBusy(true);
    try {
      setSelected(await onLoad(skill.id));
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not load this skill.');
    } finally {
      setBusy(false);
    }
  };

  const startEdit = () => {
    if (!selected) return;
    setDraft({
      name: selected.name,
      description: selected.description,
      instructions: selected.instructions,
      requiredToolIds: selected.requiredToolIds,
      visibility: selected.visibility === 'link' ? 'link' : 'private',
    });
    setMode('edit');
  };

  const startNew = () => {
    setSelected(undefined);
    setDraft(emptyDraft);
    setError('');
    setMode('new');
  };

  const save = async () => {
    if (!draft.name.trim() || !draft.description.trim() || !draft.instructions.trim()) {
      setError('Add a name, summary, and instructions.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const saved = await onSave(
        {
          ...draft,
          name: draft.name.trim(),
          description: draft.description.trim(),
          instructions: draft.instructions.trim(),
        },
        mode === 'edit' ? selected?.id : undefined,
      );
      await onChanged();
      setSelected(saved);
      setMode('view');
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not save this skill.');
    } finally {
      setBusy(false);
    }
  };

  const share = async () => {
    if (!selected) return;
    setBusy(true);
    setError('');
    try {
      const url = await onShare(selected.id);
      await Share.share({
        title: `Share ${selected.name}`,
        message: `Add the ${selected.name} skill to FrogBot: ${url}`,
        url,
      });
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not share this skill.');
    } finally {
      setBusy(false);
    }
  };

  const back = () => {
    setError('');
    setMode(mode === 'edit' || mode === 'new' ? (selected ? 'view' : 'list') : 'list');
  };

  return (
    <Modal visible animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <KeyboardAvoidingView style={styles.page} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.header}>
          <Pressable hitSlop={12} onPress={mode === 'list' ? onClose : back}>
            <Text style={styles.headerAction}>{mode === 'list' ? 'Close' : 'Back'}</Text>
          </Pressable>
          <Text style={styles.title}>{mode === 'list' ? 'Skills' : mode === 'new' ? 'New skill' : selected?.name}</Text>
          {mode === 'list' ? (
            <Pressable hitSlop={12} onPress={startNew}>
              <Text style={[styles.headerAction, styles.primary]}>New</Text>
            </Pressable>
          ) : mode === 'edit' || mode === 'new' ? (
            <Pressable hitSlop={12} disabled={busy} onPress={save}>
              {busy ? <ActivityIndicator color="#007A3D" /> : <Text style={[styles.headerAction, styles.primary]}>Save</Text>}
            </Pressable>
          ) : (
            <View style={styles.headerSpacer} />
          )}
        </View>

        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          {mode === 'list' ? (
            <>
              <Text style={styles.lead}>Give any bot a repeatable way of working. Your own skills stay private unless you share a link.</Text>
              <Text style={styles.sectionLabel}>Available</Text>
              {skills.map((skill) => (
                <Pressable key={skill.id} style={({ pressed }) => [styles.card, pressed && styles.pressed]} onPress={() => open(skill)}>
                  <View style={styles.skillMark}>
                    <Text style={styles.skillMarkText}>S</Text>
                  </View>
                  <View style={styles.cardText}>
                    <View style={styles.nameRow}>
                      <Text style={styles.skillName}>{skill.name}</Text>
                      <Text style={styles.badge}>{skill.source === 'official' ? 'FrogBot' : skill.relationship === 'owner' ? 'Yours' : 'Shared'}</Text>
                    </View>
                    <Text style={styles.skillDescription}>{skill.description}</Text>
                  </View>
                  <Text style={styles.chevron}>›</Text>
                </Pressable>
              ))}
            </>
          ) : mode === 'view' ? (
            <SkillView skill={selected} tools={tools} busy={busy} onEdit={startEdit} onShare={share} />
          ) : (
            <SkillForm draft={draft} tools={tools} onChange={setDraft} />
          )}
          {error ? <Text style={styles.error}>{error}</Text> : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function SkillView({
  skill,
  tools,
  busy,
  onEdit,
  onShare,
}: {
  skill?: SkillDetail;
  tools: Capability[];
  busy: boolean;
  onEdit: () => void;
  onShare: () => void;
}) {
  if (!skill || busy) return <ActivityIndicator style={styles.loader} color="#007A3D" />;
  return (
    <>
      <View style={styles.heroMark}>
        <Text style={styles.heroMarkText}>S</Text>
      </View>
      <Text style={styles.detailName}>{skill.name}</Text>
      <Text style={styles.detailDescription}>{skill.description}</Text>
      <View style={styles.metaRow}>
        <Text style={styles.badge}>{skill.source === 'official' ? 'FrogBot skill' : skill.editable ? 'Your skill' : 'Shared skill'}</Text>
        <Text style={styles.version}>Version {skill.version}</Text>
      </View>
      <Text style={styles.sectionLabel}>Instructions</Text>
      <View style={styles.instructionsCard}>
        <Text style={styles.instructions}>{skill.instructions}</Text>
      </View>
      {skill.requiredToolIds.length ? (
        <>
          <Text style={styles.sectionLabel}>Uses</Text>
          <View style={styles.pillRow}>
            {skill.requiredToolIds.map((id) => (
              <Text key={id} style={styles.toolPill}>
                {tools.find((tool) => tool.id === id)?.name ?? id}
              </Text>
            ))}
          </View>
        </>
      ) : null}
      <View style={styles.actionRow}>
        {skill.editable ? (
          <Pressable style={[styles.button, styles.secondaryButton]} onPress={onEdit}>
            <Text style={styles.secondaryButtonText}>Edit</Text>
          </Pressable>
        ) : null}
        <Pressable style={[styles.button, styles.primaryButton]} onPress={onShare}>
          <Text style={styles.primaryButtonText}>Share link</Text>
        </Pressable>
      </View>
    </>
  );
}

function SkillForm({ draft, tools, onChange }: { draft: SkillDraft; tools: Capability[]; onChange: (value: SkillDraft) => void }) {
  const toggleTool = (id: string) =>
    onChange({
      ...draft,
      requiredToolIds: draft.requiredToolIds.includes(id)
        ? draft.requiredToolIds.filter((value) => value !== id)
        : [...draft.requiredToolIds, id],
    });
  return (
    <>
      <Text style={styles.fieldLabel}>Name</Text>
      <TextInput
        style={styles.input}
        value={draft.name}
        onChangeText={(name) => onChange({ ...draft, name })}
        placeholder="Customer interview analyst"
        placeholderTextColor="#9B978F"
        maxLength={80}
      />
      <Text style={styles.fieldLabel}>Short summary</Text>
      <TextInput
        style={styles.input}
        value={draft.description}
        onChangeText={(description) => onChange({ ...draft, description })}
        placeholder="What this skill helps a bot do"
        placeholderTextColor="#9B978F"
        maxLength={240}
      />
      <Text style={styles.fieldLabel}>Instructions</Text>
      <TextInput
        style={[styles.input, styles.instructionsInput]}
        value={draft.instructions}
        onChangeText={(instructions) => onChange({ ...draft, instructions })}
        placeholder="Describe the steps, output, checks, and boundaries the bot should follow."
        placeholderTextColor="#9B978F"
        maxLength={20000}
        multiline
        textAlignVertical="top"
      />
      <Text style={styles.fieldLabel}>Tools this skill needs</Text>
      {tools.map((tool) => {
        const active = draft.requiredToolIds.includes(tool.id);
        return (
          <Pressable key={tool.id} style={[styles.toolRow, active && styles.toolRowActive]} onPress={() => toggleTool(tool.id)}>
            <View style={[styles.check, active && styles.checkActive]}>{active ? <Text style={styles.checkText}>✓</Text> : null}</View>
            <View style={styles.cardText}>
              <Text style={styles.toolName}>{tool.name}</Text>
              <Text style={styles.skillDescription}>{tool.description}</Text>
            </View>
          </Pressable>
        );
      })}
      <Text style={styles.fieldLabel}>Sharing</Text>
      <View style={styles.visibilityRow}>
        {(['private', 'link'] as const).map((visibility) => (
          <Pressable
            key={visibility}
            style={[styles.visibilityChoice, draft.visibility === visibility && styles.visibilityChoiceActive]}
            onPress={() => onChange({ ...draft, visibility })}>
            <Text style={[styles.visibilityText, draft.visibility === visibility && styles.visibilityTextActive]}>
              {visibility === 'private' ? 'Private' : 'Share by link'}
            </Text>
          </Pressable>
        ))}
      </View>
    </>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: '#F8F7F3' },
  header: { minHeight: 58, paddingHorizontal: 18, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: '#DDDAD2', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: '#FBFBF9' },
  headerAction: { color: '#5D5A54', fontSize: 16 },
  primary: { color: '#007A3D', fontWeight: '700' },
  title: { maxWidth: '62%', fontSize: 16, fontWeight: '700', color: '#171714' },
  headerSpacer: { width: 40 },
  content: { padding: 20, paddingBottom: 60, maxWidth: 680, width: '100%', alignSelf: 'center' },
  lead: { color: '#6F6B64', fontSize: 15, lineHeight: 22, marginBottom: 26 },
  sectionLabel: { color: '#24231F', fontSize: 13, fontWeight: '800', marginTop: 26, marginBottom: 10, textTransform: 'uppercase', letterSpacing: 0.7 },
  card: { minHeight: 76, flexDirection: 'row', alignItems: 'center', gap: 12, padding: 13, marginBottom: 9, borderRadius: 16, borderWidth: 1, borderColor: '#E2DFD7', backgroundColor: '#FFFFFF' },
  skillMark: { width: 42, height: 42, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: '#E4F1EA' },
  skillMarkText: { color: '#007A3D', fontSize: 17, fontWeight: '900' },
  cardText: { flex: 1, minWidth: 0 },
  nameRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  skillName: { flexShrink: 1, color: '#24231F', fontSize: 15, fontWeight: '700' },
  skillDescription: { color: '#7B776F', fontSize: 12, lineHeight: 17, marginTop: 4 },
  badge: { alignSelf: 'flex-start', color: '#007A3D', backgroundColor: '#E4F1EA', overflow: 'hidden', borderRadius: 8, paddingHorizontal: 7, paddingVertical: 3, fontSize: 10, fontWeight: '700' },
  chevron: { color: '#9A968E', fontSize: 27, fontWeight: '300' },
  heroMark: { alignSelf: 'center', width: 68, height: 68, borderRadius: 22, alignItems: 'center', justifyContent: 'center', backgroundColor: '#007A3D', marginTop: 14 },
  heroMarkText: { color: 'white', fontSize: 25, fontWeight: '900' },
  detailName: { color: '#1E1D19', fontSize: 25, fontWeight: '800', textAlign: 'center', marginTop: 15 },
  detailDescription: { color: '#716D66', fontSize: 15, lineHeight: 21, textAlign: 'center', marginTop: 7 },
  metaRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 9, marginTop: 13 },
  version: { color: '#8B877F', fontSize: 11 },
  instructionsCard: { padding: 16, borderRadius: 15, borderWidth: 1, borderColor: '#E2DFD7', backgroundColor: 'white' },
  instructions: { color: '#302F2A', fontSize: 14, lineHeight: 21 },
  pillRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  toolPill: { color: '#46433D', backgroundColor: '#ECEAE5', overflow: 'hidden', borderRadius: 12, paddingHorizontal: 11, paddingVertical: 7, fontSize: 12, fontWeight: '600' },
  actionRow: { flexDirection: 'row', gap: 10, marginTop: 32 },
  button: { flex: 1, minHeight: 47, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  primaryButton: { backgroundColor: '#007A3D' },
  primaryButtonText: { color: 'white', fontSize: 14, fontWeight: '700' },
  secondaryButton: { borderWidth: 1, borderColor: '#D9D6CF', backgroundColor: 'white' },
  secondaryButtonText: { color: '#35332E', fontSize: 14, fontWeight: '700' },
  fieldLabel: { color: '#24231F', fontSize: 14, fontWeight: '700', marginTop: 20, marginBottom: 8 },
  input: { minHeight: 48, paddingHorizontal: 14, paddingVertical: 12, borderRadius: 14, borderWidth: 1, borderColor: '#DDDAD2', backgroundColor: 'white', color: '#24231F', fontSize: 15 },
  instructionsInput: { minHeight: 210, lineHeight: 21 },
  toolRow: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 13, marginBottom: 8, borderRadius: 14, borderWidth: 1, borderColor: '#E2DFD7', backgroundColor: 'white' },
  toolRowActive: { borderColor: '#8AB99F', backgroundColor: '#EAF5EF' },
  toolName: { color: '#2B2A25', fontSize: 14, fontWeight: '700' },
  check: { width: 22, height: 22, borderRadius: 7, borderWidth: 1, borderColor: '#C9C5BD', alignItems: 'center', justifyContent: 'center' },
  checkActive: { backgroundColor: '#007A3D', borderColor: '#007A3D' },
  checkText: { color: 'white', fontSize: 14, fontWeight: '800' },
  visibilityRow: { flexDirection: 'row', padding: 4, borderRadius: 14, backgroundColor: '#E9E7E1' },
  visibilityChoice: { flex: 1, minHeight: 40, borderRadius: 11, alignItems: 'center', justifyContent: 'center' },
  visibilityChoiceActive: { backgroundColor: 'white' },
  visibilityText: { color: '#77736B', fontSize: 13, fontWeight: '600' },
  visibilityTextActive: { color: '#007A3D' },
  loader: { marginTop: 80 },
  error: { color: '#A43C31', fontSize: 13, lineHeight: 18, marginTop: 16 },
  pressed: { opacity: 0.7 },
});
