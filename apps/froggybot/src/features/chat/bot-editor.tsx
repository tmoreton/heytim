import { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { BotAvatar } from '@/components/bot-avatar';
import { BOT_COLORS, CHIEF_COLOR, displayBotColor } from '@/lib/bot-branding';
import type { Bot, BotDraft, Capability, CapabilitySelection, Skill, SkillDetail } from '@/lib/types';

const emptyDraft: BotDraft = {
  name: '',
  tagline: '',
  prompt: '',
  color: BOT_COLORS[0],
  toolIds: [],
  skillIds: [],
};

type Props = {
  bot?: Bot;
  tools: Capability[];
  skills: Skill[];
  suggestedCapability?: CapabilitySelection;
  onClose: () => void;
  onSave: (draft: BotDraft) => Promise<void>;
  onLoadSkill: (skillId: string) => Promise<SkillDetail>;
};

const extraToolsForBot = (bot: Bot, skills: Skill[]) => {
  if (bot.extraToolIds) return bot.extraToolIds;
  const required = new Set(
    skills
      .filter((skill) => bot.skillIds.includes(skill.id))
      .flatMap((skill) => skill.requiredToolIds),
  );
  return bot.toolIds.filter((toolId) => !required.has(toolId));
};

const botDraft = (
  bot: Bot | undefined,
  skills: Skill[],
  tools: Capability[],
  suggested?: CapabilitySelection,
): BotDraft => {
  const draft = bot
    ? {
        name: bot.name,
        tagline: bot.tagline,
        prompt: bot.prompt,
        color: displayBotColor(bot),
        toolIds: extraToolsForBot(bot, skills),
        skillIds: bot.skillIds,
      }
    : emptyDraft;
  if (suggested?.kind === 'skill' && skills.some((skill) => skill.id === suggested.id)) {
    return { ...draft, skillIds: [...new Set([...draft.skillIds, suggested.id])] };
  }
  if (suggested?.kind === 'tool' && tools.some((tool) => tool.id === suggested.id)) {
    return { ...draft, toolIds: [...new Set([...draft.toolIds, suggested.id])] };
  }
  return draft;
};

export function BotEditor({ bot, tools, skills, suggestedCapability, onClose, onSave, onLoadSkill }: Props) {
  const [draft, setDraft] = useState<BotDraft>(() => botDraft(bot, skills, tools, suggestedCapability));
  const [skillDetails, setSkillDetails] = useState<Record<string, SkillDetail>>({});
  const [expandedSkillId, setExpandedSkillId] = useState<string>();
  const [loadingSkillId, setLoadingSkillId] = useState<string>();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const chief = bot?.systemRole === 'chief';
  const colorChoices = chief ? [CHIEF_COLOR] : BOT_COLORS;

  const selectedSkills = skills.filter((skill) => draft.skillIds.includes(skill.id));
  const requiredByTool = new Map<string, string[]>();
  selectedSkills.forEach((skill) => {
    skill.requiredToolIds.forEach((toolId) => {
      requiredByTool.set(toolId, [...(requiredByTool.get(toolId) ?? []), skill.name]);
    });
  });
  const effectiveToolCount = new Set([...draft.toolIds, ...requiredByTool.keys()]).size;
  const suggestedItem = suggestedCapability?.kind === 'skill'
    ? skills.find((skill) => skill.id === suggestedCapability.id)
    : tools.find((tool) => tool.id === suggestedCapability?.id);

  const toggleTool = (id: string) => {
    if (requiredByTool.has(id)) return;
    setDraft((current) => ({
      ...current,
      toolIds: current.toolIds.includes(id)
        ? current.toolIds.filter((value) => value !== id)
        : [...current.toolIds, id],
    }));
  };

  const toggleSkill = (id: string) => {
    setDraft((current) => ({
      ...current,
      skillIds: current.skillIds.includes(id)
        ? current.skillIds.filter((value) => value !== id)
        : [...current.skillIds, id],
    }));
  };

  const toggleSkillDetails = async (skill: Skill) => {
    if (expandedSkillId === skill.id) {
      setExpandedSkillId(undefined);
      return;
    }
    setExpandedSkillId(skill.id);
    setError('');
    if (skillDetails[skill.id]) return;
    setLoadingSkillId(skill.id);
    try {
      const detail = await onLoadSkill(skill.id);
      setSkillDetails((current) => ({ ...current, [skill.id]: detail }));
    } catch (value) {
      setExpandedSkillId(undefined);
      setError(value instanceof Error ? value.message : 'Could not load the full skill.');
    } finally {
      setLoadingSkillId(undefined);
    }
  };

  const save = async () => {
    if (!draft.name.trim() || !draft.prompt.trim()) {
      setError('Give your bot a name and a prompt.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      await onSave({ ...draft, name: draft.name.trim(), tagline: draft.tagline.trim(), prompt: draft.prompt.trim() });
      onClose();
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not save this bot.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <KeyboardAvoidingView style={styles.page} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.header}>
          <Pressable accessibilityRole="button" hitSlop={12} onPress={onClose}>
            <Text style={styles.headerAction}>Cancel</Text>
          </Pressable>
          <Text style={styles.title}>{bot ? 'Edit bot' : 'New bot'}</Text>
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ busy: saving, disabled: saving }}
            hitSlop={12}
            disabled={saving}
            onPress={save}>
            {saving ? <ActivityIndicator color="#007A3D" /> : <Text style={[styles.headerAction, styles.save]}>Save</Text>}
          </Pressable>
        </View>

        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          {suggestedItem ? (
            <View style={styles.suggestion}>
              <Text style={styles.suggestionTitle}>{suggestedItem.name} is selected</Text>
              <Text style={styles.suggestionText}>Review this FroggyBot, then save to add it.</Text>
            </View>
          ) : null}
          <View style={styles.identity}>
            <BotAvatar name={draft.name || 'New bot'} color={draft.color} size={64} />
            <View style={styles.identityText}>
              <TextInput
                accessibilityLabel="Bot name"
                style={styles.nameInput}
                value={draft.name}
                onChangeText={(name) => setDraft((value) => ({ ...value, name }))}
                placeholder="Bot name"
                placeholderTextColor="#A4A098"
                maxLength={48}
              />
              <TextInput
                accessibilityLabel="One-line bot description"
                style={styles.taglineInput}
                value={draft.tagline}
                onChangeText={(tagline) => setDraft((value) => ({ ...value, tagline }))}
                placeholder="What this bot is best at"
                placeholderTextColor="#A4A098"
                maxLength={120}
              />
            </View>
          </View>

          <Text style={styles.label}>Color</Text>
          <View style={styles.colorRow}>
            {colorChoices.map((color) => (
              <Pressable
                key={color}
                accessibilityLabel={chief ? 'FroggyBot green, reserved for Chief' : `Use color ${color}`}
                accessibilityRole="button"
                accessibilityState={{ selected: draft.color === color, disabled: chief }}
                disabled={chief}
                style={[styles.color, { backgroundColor: color }, draft.color === color && styles.colorSelected]}
                onPress={() => setDraft((value) => ({ ...value, color }))}
              />
            ))}
          </View>
          <Text style={[styles.sectionSubtitle, styles.colorNote]}>
            {chief ? 'Chief always uses FroggyBot green.' : 'FroggyBot green is reserved for Chief.'}
          </Text>

          <Text style={styles.label}>Bot prompt</Text>
          <Text style={styles.sectionSubtitle}>
            Editable any time. Include the accounts or handles it should follow, plus its role, priorities, tone, and
            boundaries.
          </Text>
          <TextInput
            accessibilityLabel="Full bot prompt"
            style={styles.promptInput}
            value={draft.prompt}
            onChangeText={(prompt) => setDraft((value) => ({ ...value, prompt }))}
            placeholder="Act as my… Focus on account @… Always… Never… Keep responses…"
            placeholderTextColor="#A4A098"
            multiline
            textAlignVertical="top"
            maxLength={12000}
          />
          <Text style={styles.characterCount}>{draft.prompt.length.toLocaleString()} / 12,000</Text>

          <View style={styles.guide}>
            <Text style={styles.guideTitle}>What happens when you chat</Text>
            <Text style={styles.guideText}>The prompt is always active. The model then chooses a matching skill and calls its full instructions. It uses an available tool only when the request needs it.</Text>
            <Text style={styles.guideStrong}>Ask normally—you do not need special commands.</Text>
          </View>

          <View style={styles.sectionHeading}>
            <View>
              <Text style={styles.label}>Skills</Text>
              <Text style={styles.sectionSubtitle}>Playbooks this bot can activate automatically</Text>
            </View>
            <Text style={styles.count}>{draft.skillIds.length} selected</Text>
          </View>
          {skills.map((skill) => {
            const active = draft.skillIds.includes(skill.id);
            const expanded = expandedSkillId === skill.id;
            const detail = skillDetails[skill.id];
            return (
              <View key={skill.id} style={[styles.capability, active && styles.capabilityActive]}>
                <View style={styles.capabilityTop}>
                  <Pressable
                    accessibilityRole="checkbox"
                    accessibilityState={{ checked: active }}
                    hitSlop={8}
                    style={[styles.check, active && styles.checkActive]}
                    onPress={() => toggleSkill(skill.id)}>
                    {active ? <Text style={styles.checkMark}>✓</Text> : null}
                  </Pressable>
                  <Pressable
                    accessibilityRole="checkbox"
                    accessibilityState={{ checked: active }}
                    style={styles.capabilityText}
                    onPress={() => toggleSkill(skill.id)}>
                    <Text style={styles.capabilityName}>{skill.name}</Text>
                    <Text style={styles.capabilityDescription}>{skill.description}</Text>
                    <Text style={styles.capabilityMeta}>
                      {skill.requiredToolIds.length
                        ? `Adds ${skill.requiredToolIds.length} required ${skill.requiredToolIds.length === 1 ? 'tool' : 'tools'}`
                        : 'No tools required'}
                    </Text>
                  </Pressable>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityState={{ expanded }}
                    hitSlop={8}
                    style={styles.detailsButton}
                    onPress={() => toggleSkillDetails(skill)}>
                    {loadingSkillId === skill.id ? (
                      <ActivityIndicator color="#007A3D" size="small" />
                    ) : (
                      <Text style={styles.detailsButtonText}>{expanded ? 'Hide' : 'View'}</Text>
                    )}
                  </Pressable>
                </View>
                {expanded && detail ? (
                  <View style={styles.skillDetail}>
                    <Text style={styles.skillDetailLabel}>Full instructions</Text>
                    <Text selectable style={styles.skillInstructions}>{detail.instructions}</Text>
                    <Text style={styles.skillDetailLabel}>Required tools</Text>
                    <Text style={styles.skillToolList}>
                      {detail.requiredToolIds.length
                        ? detail.requiredToolIds.map((id) => tools.find((tool) => tool.id === id)?.name ?? id).join(' · ')
                        : 'None'}
                    </Text>
                  </View>
                ) : null}
              </View>
            );
          })}

          <View style={styles.sectionHeading}>
            <View>
              <Text style={styles.label}>Extra tools</Text>
              <Text style={styles.sectionSubtitle}>Additional actions this bot may use when helpful</Text>
            </View>
            <Text style={styles.count}>{effectiveToolCount} available</Text>
          </View>
          {tools.map((tool) => {
            const requiredBy = requiredByTool.get(tool.id) ?? [];
            const required = requiredBy.length > 0;
            const active = required || draft.toolIds.includes(tool.id);
            return (
              <Pressable
                key={tool.id}
                accessibilityRole="checkbox"
                accessibilityState={{ checked: active, disabled: required }}
                disabled={required}
                style={[styles.tool, active && styles.capabilityActive, required && styles.requiredTool]}
                onPress={() => toggleTool(tool.id)}>
                <View style={[styles.check, active && styles.checkActive]}>{active ? <Text style={styles.checkMark}>✓</Text> : null}</View>
                <View style={styles.capabilityText}>
                  <Text style={styles.capabilityName}>{tool.name}</Text>
                  <Text style={styles.capabilityDescription}>{tool.description}</Text>
                  <Text style={[styles.capabilityMeta, required && styles.requiredMeta]}>
                    {required ? `Required by ${requiredBy.join(', ')}` : 'The model calls this automatically when needed'}
                  </Text>
                </View>
              </Pressable>
            );
          })}
          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
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
  content: { padding: 20, paddingBottom: 60, maxWidth: 680, width: '100%', alignSelf: 'center' },
  suggestion: { padding: 14, marginBottom: 18, borderRadius: 15, borderWidth: 1, borderColor: '#BFDCCA', backgroundColor: '#E7F3EC' },
  suggestionTitle: { color: '#135C34', fontSize: 14, fontWeight: '800' },
  suggestionText: { color: '#557463', fontSize: 12, marginTop: 3 },
  identity: { flexDirection: 'row', alignItems: 'center', gap: 15, marginBottom: 26 },
  identityText: { flex: 1, gap: 7 },
  nameInput: { fontSize: 23, fontWeight: '700', color: '#171714', padding: 0 },
  taglineInput: { fontSize: 14, color: '#716E67', padding: 0 },
  label: { fontSize: 14, fontWeight: '700', color: '#24231F', marginBottom: 8 },
  colorRow: { flexDirection: 'row', gap: 12, marginBottom: 8 },
  color: { width: 32, height: 32, borderRadius: 16, borderWidth: 3, borderColor: '#F8F7F3' },
  colorSelected: { borderColor: '#007A3D' },
  colorNote: { marginTop: 0, marginBottom: 26 },
  promptInput: { minHeight: 190, padding: 15, borderRadius: 15, borderWidth: 1, borderColor: '#DDDAD2', backgroundColor: 'white', color: '#24231F', fontSize: 15, lineHeight: 21 },
  characterCount: { color: '#9B978F', fontSize: 11, textAlign: 'right', marginTop: 5 },
  guide: { padding: 16, borderRadius: 17, backgroundColor: '#E9F4EE', borderWidth: 1, borderColor: '#CBE2D5', marginTop: 24 },
  guideTitle: { color: '#173E2A', fontSize: 15, fontWeight: '800' },
  guideText: { color: '#567162', fontSize: 13, lineHeight: 19, marginTop: 5 },
  guideStrong: { color: '#007A3D', fontSize: 12, fontWeight: '800', marginTop: 8 },
  sectionHeading: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, marginTop: 28 },
  sectionSubtitle: { color: '#858179', fontSize: 13, lineHeight: 18, marginTop: -4, marginBottom: 10 },
  count: { color: '#007A3D', fontSize: 11, fontWeight: '700', marginTop: 2 },
  capability: { padding: 13, borderRadius: 14, marginBottom: 8, backgroundColor: 'white', borderWidth: 1, borderColor: '#E4E1DA' },
  capabilityTop: { flexDirection: 'row', gap: 12, alignItems: 'flex-start' },
  tool: { flexDirection: 'row', gap: 12, alignItems: 'center', padding: 13, borderRadius: 14, marginBottom: 8, backgroundColor: 'white', borderWidth: 1, borderColor: '#E4E1DA' },
  capabilityActive: { borderColor: '#8AB99F', backgroundColor: '#EAF5EF' },
  requiredTool: { opacity: 0.92 },
  check: { width: 22, height: 22, borderRadius: 7, borderWidth: 1, borderColor: '#C9C5BD', alignItems: 'center', justifyContent: 'center', marginTop: 1 },
  checkActive: { backgroundColor: '#007A3D', borderColor: '#007A3D' },
  checkMark: { color: 'white', fontSize: 14, fontWeight: '800' },
  capabilityText: { flex: 1, minWidth: 0 },
  capabilityName: { fontSize: 15, color: '#24231F', fontWeight: '700' },
  capabilityDescription: { fontSize: 13, lineHeight: 18, color: '#77736B', marginTop: 2 },
  capabilityMeta: { fontSize: 10.5, lineHeight: 15, color: '#99958C', marginTop: 5 },
  requiredMeta: { color: '#007A3D', fontWeight: '700' },
  detailsButton: { minWidth: 46, minHeight: 30, alignItems: 'center', justifyContent: 'center' },
  detailsButtonText: { color: '#007A3D', fontSize: 12, fontWeight: '800' },
  skillDetail: { borderTopWidth: 1, borderColor: '#CFE0D6', marginTop: 13, paddingTop: 13 },
  skillDetailLabel: { color: '#466454', fontSize: 10, fontWeight: '800', letterSpacing: 0.55, textTransform: 'uppercase', marginBottom: 5, marginTop: 4 },
  skillInstructions: { color: '#302F2A', fontSize: 13, lineHeight: 20 },
  skillToolList: { color: '#007A3D', fontSize: 12, lineHeight: 18, fontWeight: '700' },
  error: { color: '#B83C32', marginTop: 16 },
});
