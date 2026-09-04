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

type LibraryTab = 'skills' | 'tools';

type Props = {
  skills: Skill[];
  tools: Capability[];
  onClose: () => void;
  onLoad: (skillId: string) => Promise<SkillDetail>;
  onSave: (draft: SkillDraft, skillId?: string) => Promise<SkillDetail>;
  onShare: (skillId: string) => Promise<string>;
  onChanged: () => Promise<void>;
};

const providerLabel = (provider?: string) => {
  if (provider === 'stan') return 'Stan';
  if (provider === 'agentcore') return 'AgentCore';
  if (provider === 'agentcore-gateway') return 'Connected service';
  return 'FrogBot';
};

export function SkillLibrary({ skills, tools, onClose, onLoad, onSave, onShare, onChanged }: Props) {
  const [selected, setSelected] = useState<SkillDetail>();
  const [draft, setDraft] = useState<SkillDraft>(emptyDraft);
  const [mode, setMode] = useState<'list' | 'view' | 'edit' | 'copy' | 'new'>('list');
  const [tab, setTab] = useState<LibraryTab>('skills');
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

  const startCustomize = () => {
    if (!selected) return;
    setDraft({
      name: `${selected.name} copy`,
      description: selected.description,
      instructions: selected.instructions,
      requiredToolIds: selected.requiredToolIds,
      visibility: 'private',
    });
    setMode('copy');
  };

  const startNew = () => {
    setSelected(undefined);
    setDraft(emptyDraft);
    setError('');
    setMode('new');
  };

  const save = async () => {
    if (!draft.name.trim() || !draft.description.trim() || !draft.instructions.trim()) {
      setError('Add a name, summary, and full instructions.');
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
    setMode(mode === 'edit' || mode === 'copy' || mode === 'new' ? (selected ? 'view' : 'list') : 'list');
  };

  const title =
    mode === 'list'
      ? 'Skills & tools'
      : mode === 'new'
        ? 'New skill'
        : mode === 'copy'
          ? 'Make editable copy'
          : selected?.name;

  return (
    <Modal visible animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <KeyboardAvoidingView style={styles.page} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.header}>
          <Pressable accessibilityRole="button" hitSlop={12} onPress={mode === 'list' ? onClose : back}>
            <Text style={styles.headerAction}>{mode === 'list' ? 'Close' : 'Back'}</Text>
          </Pressable>
          <Text numberOfLines={1} style={styles.title}>{title}</Text>
          {mode === 'list' ? (
            <Pressable accessibilityRole="button" hitSlop={12} onPress={startNew}>
              <Text style={[styles.headerAction, styles.primary]}>New skill</Text>
            </Pressable>
          ) : mode === 'edit' || mode === 'copy' || mode === 'new' ? (
            <Pressable
              accessibilityRole="button"
              accessibilityState={{ busy, disabled: busy }}
              hitSlop={12}
              disabled={busy}
              onPress={save}>
              {busy ? <ActivityIndicator color="#007A3D" /> : <Text style={[styles.headerAction, styles.primary]}>Save</Text>}
            </Pressable>
          ) : (
            <View style={styles.headerSpacer} />
          )}
        </View>

        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          {mode === 'list' ? (
            <>
              <HowItWorks />
              <View accessibilityRole="tablist" style={styles.tabs}>
                {(['skills', 'tools'] as const).map((value) => (
                  <Pressable
                    key={value}
                    accessibilityRole="tab"
                    accessibilityState={{ selected: tab === value }}
                    style={[styles.tab, tab === value && styles.tabActive]}
                    onPress={() => setTab(value)}>
                    <Text style={[styles.tabText, tab === value && styles.tabTextActive]}>
                      {value === 'skills' ? `Skills · ${skills.length}` : `Tools · ${tools.length}`}
                    </Text>
                  </Pressable>
                ))}
              </View>
              {tab === 'skills' ? (
                <>
                  <Text style={styles.sectionLabel}>Available skills</Text>
                  {skills.map((skill) => (
                    <Pressable
                      accessibilityRole="button"
                      key={skill.id}
                      style={({ pressed }) => [styles.card, pressed && styles.pressed]}
                      onPress={() => open(skill)}>
                      <View style={styles.skillMark}><Text style={styles.skillMarkText}>S</Text></View>
                      <View style={styles.cardText}>
                        <View style={styles.nameRow}>
                          <Text style={styles.skillName}>{skill.name}</Text>
                          <Text style={styles.badge}>
                            {skill.source === 'official' ? 'FrogBot' : skill.relationship === 'owner' ? 'Yours' : 'Shared'}
                          </Text>
                        </View>
                        <Text style={styles.skillDescription}>{skill.description}</Text>
                        <Text style={styles.cardMeta}>
                          {skill.requiredToolIds.length
                            ? `${skill.requiredToolIds.length} required ${skill.requiredToolIds.length === 1 ? 'tool' : 'tools'}`
                            : 'No tools required'}
                        </Text>
                      </View>
                      <Text style={styles.chevron}>›</Text>
                    </Pressable>
                  ))}
                </>
              ) : (
                <>
                  <Text style={styles.sectionLabel}>Ready to use</Text>
                  <Text style={styles.listHelp}>
                    These are the tools connected and working now. A bot only receives tools you choose or that one of its skills requires.
                  </Text>
                  {tools.map((tool) => (
                    <View key={tool.id} style={styles.card}>
                      <View style={styles.toolMark}><Text style={styles.toolMarkText}>T</Text></View>
                      <View style={styles.cardText}>
                        <View style={styles.nameRow}>
                          <Text style={styles.skillName}>{tool.name}</Text>
                          <Text style={styles.neutralBadge}>{providerLabel(tool.provider)}</Text>
                        </View>
                        <Text style={styles.skillDescription}>{tool.description}</Text>
                        <Text style={styles.cardMeta}>Called automatically when it helps answer the request</Text>
                      </View>
                    </View>
                  ))}
                </>
              )}
            </>
          ) : mode === 'view' ? (
            <SkillView
              skill={selected}
              tools={tools}
              busy={busy}
              onEdit={startEdit}
              onCustomize={startCustomize}
              onShare={share}
            />
          ) : (
            <SkillForm draft={draft} tools={tools} onChange={setDraft} />
          )}
          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function HowItWorks() {
  return (
    <View style={styles.guide}>
      <Text style={styles.guideTitle}>How capabilities work</Text>
      <Text style={styles.guideLine}><Text style={styles.guideStrong}>Bot prompt</Text> · always guides every reply.</Text>
      <Text style={styles.guideLine}><Text style={styles.guideStrong}>Skills</Text> · full playbooks the bot activates when the request matches.</Text>
      <Text style={styles.guideLine}><Text style={styles.guideStrong}>Tools</Text> · actions the bot calls when needed.</Text>
      <Text style={styles.guideNote}>Ask normally—you never have to name a skill or tool.</Text>
    </View>
  );
}

function SkillView({
  skill,
  tools,
  busy,
  onEdit,
  onCustomize,
  onShare,
}: {
  skill?: SkillDetail;
  tools: Capability[];
  busy: boolean;
  onEdit: () => void;
  onCustomize: () => void;
  onShare: () => void;
}) {
  if (!skill || busy) return <ActivityIndicator style={styles.loader} color="#007A3D" />;
  const ownershipNote = skill.editable
    ? 'You own this skill. Changes create a new version.'
    : skill.source === 'official'
      ? 'Maintained by FrogBot. Make an editable copy to change it.'
      : 'Installed from a shared link. Make an editable copy to change it.';
  return (
    <>
      <View style={styles.heroMark}><Text style={styles.heroMarkText}>S</Text></View>
      <Text style={styles.detailName}>{skill.name}</Text>
      <Text style={styles.detailDescription}>{skill.description}</Text>
      <View style={styles.metaRow}>
        <Text style={styles.badge}>{skill.source === 'official' ? 'FrogBot skill' : skill.editable ? 'Your skill' : 'Shared skill'}</Text>
        <Text style={styles.version}>Version {skill.version}</Text>
      </View>
      <Text style={styles.detailNote}>{ownershipNote}</Text>

      <Text style={styles.sectionLabel}>Full instructions</Text>
      <Text style={styles.listHelp}>
        The model sees the summary first, then automatically loads this complete prompt when the skill fits your request.
      </Text>
      <View style={styles.instructionsCard}>
        <Text selectable style={styles.instructions}>{skill.instructions}</Text>
      </View>

      <Text style={styles.sectionLabel}>Required tools</Text>
      {skill.requiredToolIds.length ? (
        <View style={styles.pillRow}>
          {skill.requiredToolIds.map((id) => (
            <Text key={id} style={styles.toolPill}>{tools.find((tool) => tool.id === id)?.name ?? id}</Text>
          ))}
        </View>
      ) : (
        <Text style={styles.noTools}>None. This skill works from its instructions alone.</Text>
      )}

      <View style={styles.actionRow}>
        <Pressable accessibilityRole="button" style={[styles.button, styles.secondaryButton]} onPress={skill.editable ? onEdit : onCustomize}>
          <Text style={styles.secondaryButtonText}>{skill.editable ? 'Edit full skill' : 'Make editable copy'}</Text>
        </Pressable>
        <Pressable accessibilityRole="button" style={[styles.button, styles.primaryButton]} onPress={onShare}>
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
      <View style={styles.formIntro}>
        <Text style={styles.formIntroTitle}>Write a reusable playbook</Text>
        <Text style={styles.formIntroText}>
          The summary helps the model decide when to activate it. The full instructions tell the bot exactly how to work.
        </Text>
      </View>
      <Text style={styles.fieldLabel}>Name</Text>
      <TextInput
        accessibilityLabel="Skill name"
        style={styles.input}
        value={draft.name}
        onChangeText={(name) => onChange({ ...draft, name })}
        placeholder="Customer interview analyst"
        placeholderTextColor="#9B978F"
        maxLength={80}
      />
      <Text style={styles.fieldLabel}>When should the bot use it?</Text>
      <TextInput
        accessibilityLabel="Skill activation summary"
        style={styles.input}
        value={draft.description}
        onChangeText={(description) => onChange({ ...draft, description })}
        placeholder="Analyze interview notes and identify recurring themes"
        placeholderTextColor="#9B978F"
        maxLength={240}
      />
      <Text style={styles.fieldLabel}>Full instructions</Text>
      <Text style={styles.fieldHelp}>Include the steps, expected output, checks, and boundaries. The complete text is sent to the bot when activated.</Text>
      <TextInput
        accessibilityLabel="Full skill instructions"
        style={[styles.input, styles.instructionsInput]}
        value={draft.instructions}
        onChangeText={(instructions) => onChange({ ...draft, instructions })}
        placeholder="1. Identify the decision…\n2. Group evidence into themes…\n3. Return findings with confidence and gaps…"
        placeholderTextColor="#9B978F"
        maxLength={20000}
        multiline
        textAlignVertical="top"
      />
      <Text style={styles.characterCount}>{draft.instructions.length.toLocaleString()} / 20,000</Text>
      <Text style={styles.fieldLabel}>Tools required by this skill</Text>
      <Text style={styles.fieldHelp}>Selected tools are added automatically to every bot using the skill.</Text>
      {tools.map((tool) => {
        const active = draft.requiredToolIds.includes(tool.id);
        return (
          <Pressable
            key={tool.id}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: active }}
            style={[styles.toolRow, active && styles.toolRowActive]}
            onPress={() => toggleTool(tool.id)}>
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
            accessibilityRole="radio"
            accessibilityState={{ checked: draft.visibility === visibility }}
            style={[styles.visibilityChoice, draft.visibility === visibility && styles.visibilityChoiceActive]}
            onPress={() => onChange({ ...draft, visibility })}>
            <Text style={[styles.visibilityText, draft.visibility === visibility && styles.visibilityTextActive]}>
              {visibility === 'private' ? 'Private' : 'Share by link'}
            </Text>
          </Pressable>
        ))}
      </View>
      <Text style={styles.fieldHelp}>
        A shared skill contains these instructions and tool choices, but never credentials or executable code.
      </Text>
    </>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: '#F8F7F3' },
  header: { minHeight: 58, paddingHorizontal: 18, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: '#DDDAD2', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: '#FBFBF9' },
  headerAction: { color: '#5D5A54', fontSize: 15 },
  primary: { color: '#007A3D', fontWeight: '700' },
  title: { maxWidth: '48%', fontSize: 16, fontWeight: '700', color: '#171714' },
  headerSpacer: { width: 62 },
  content: { padding: 20, paddingBottom: 60, maxWidth: 680, width: '100%', alignSelf: 'center' },
  guide: { padding: 17, borderRadius: 18, backgroundColor: '#E9F4EE', borderWidth: 1, borderColor: '#CBE2D5' },
  guideTitle: { color: '#173E2A', fontSize: 16, fontWeight: '800', marginBottom: 8 },
  guideLine: { color: '#527060', fontSize: 13, lineHeight: 20 },
  guideStrong: { color: '#173E2A', fontWeight: '800' },
  guideNote: { color: '#007A3D', fontSize: 12, fontWeight: '700', marginTop: 9 },
  tabs: { flexDirection: 'row', padding: 4, borderRadius: 14, backgroundColor: '#E9E7E1', marginTop: 18 },
  tab: { flex: 1, minHeight: 42, borderRadius: 11, alignItems: 'center', justifyContent: 'center' },
  tabActive: { backgroundColor: '#FFFFFF' },
  tabText: { color: '#77736B', fontSize: 13, fontWeight: '700' },
  tabTextActive: { color: '#007A3D' },
  sectionLabel: { color: '#24231F', fontSize: 13, fontWeight: '800', marginTop: 26, marginBottom: 10, textTransform: 'uppercase', letterSpacing: 0.7 },
  listHelp: { color: '#7B776F', fontSize: 13, lineHeight: 19, marginTop: -4, marginBottom: 12 },
  card: { minHeight: 76, flexDirection: 'row', alignItems: 'center', gap: 12, padding: 13, marginBottom: 9, borderRadius: 16, borderWidth: 1, borderColor: '#E2DFD7', backgroundColor: '#FFFFFF' },
  skillMark: { width: 42, height: 42, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: '#E4F1EA' },
  skillMarkText: { color: '#007A3D', fontSize: 17, fontWeight: '900' },
  toolMark: { width: 42, height: 42, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: '#EFEEE9' },
  toolMarkText: { color: '#57534C', fontSize: 17, fontWeight: '900' },
  cardText: { flex: 1, minWidth: 0 },
  nameRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8 },
  skillName: { flexShrink: 1, color: '#24231F', fontSize: 15, fontWeight: '700' },
  skillDescription: { color: '#7B776F', fontSize: 12, lineHeight: 17, marginTop: 4 },
  cardMeta: { color: '#918D84', fontSize: 10.5, lineHeight: 15, marginTop: 5 },
  badge: { alignSelf: 'flex-start', color: '#007A3D', backgroundColor: '#E4F1EA', overflow: 'hidden', borderRadius: 8, paddingHorizontal: 7, paddingVertical: 3, fontSize: 10, fontWeight: '700' },
  neutralBadge: { alignSelf: 'flex-start', color: '#66625B', backgroundColor: '#EFEEE9', overflow: 'hidden', borderRadius: 8, paddingHorizontal: 7, paddingVertical: 3, fontSize: 10, fontWeight: '700' },
  chevron: { color: '#9A968E', fontSize: 27, fontWeight: '300' },
  heroMark: { alignSelf: 'center', width: 68, height: 68, borderRadius: 22, alignItems: 'center', justifyContent: 'center', backgroundColor: '#007A3D', marginTop: 14 },
  heroMarkText: { color: 'white', fontSize: 25, fontWeight: '900' },
  detailName: { color: '#1E1D19', fontSize: 25, fontWeight: '800', textAlign: 'center', marginTop: 15 },
  detailDescription: { color: '#716D66', fontSize: 15, lineHeight: 21, textAlign: 'center', marginTop: 7 },
  metaRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 9, marginTop: 13 },
  version: { color: '#8B877F', fontSize: 11 },
  detailNote: { color: '#8B877F', fontSize: 12, lineHeight: 17, textAlign: 'center', marginTop: 9 },
  instructionsCard: { padding: 16, borderRadius: 15, borderWidth: 1, borderColor: '#D8D5CE', backgroundColor: '#FFFFFF' },
  instructions: { color: '#302F2A', fontSize: 14, lineHeight: 21 },
  pillRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  toolPill: { color: '#075A31', backgroundColor: '#E4F1EA', overflow: 'hidden', borderRadius: 12, paddingHorizontal: 11, paddingVertical: 7, fontSize: 12, fontWeight: '700' },
  noTools: { color: '#858179', fontSize: 13, lineHeight: 19 },
  actionRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginTop: 32 },
  button: { flexGrow: 1, flexBasis: 190, minHeight: 47, borderRadius: 14, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 12 },
  primaryButton: { backgroundColor: '#007A3D' },
  primaryButtonText: { color: 'white', fontSize: 14, fontWeight: '700' },
  secondaryButton: { borderWidth: 1, borderColor: '#D9D6CF', backgroundColor: 'white' },
  secondaryButtonText: { color: '#35332E', fontSize: 14, fontWeight: '700' },
  formIntro: { padding: 16, borderRadius: 17, backgroundColor: '#E9F4EE', marginBottom: 4 },
  formIntroTitle: { color: '#173E2A', fontSize: 15, fontWeight: '800' },
  formIntroText: { color: '#587363', fontSize: 13, lineHeight: 19, marginTop: 4 },
  fieldLabel: { color: '#24231F', fontSize: 14, fontWeight: '700', marginTop: 20, marginBottom: 8 },
  fieldHelp: { color: '#858179', fontSize: 12, lineHeight: 17, marginTop: -4, marginBottom: 9 },
  input: { minHeight: 48, paddingHorizontal: 14, paddingVertical: 12, borderRadius: 14, borderWidth: 1, borderColor: '#DDDAD2', backgroundColor: 'white', color: '#24231F', fontSize: 15 },
  instructionsInput: { minHeight: 260, lineHeight: 21 },
  characterCount: { color: '#9B978F', fontSize: 11, textAlign: 'right', marginTop: 5 },
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
