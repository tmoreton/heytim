import { ActivityIndicator, Pressable, Text, TextInput, View } from 'react-native';

import { requiredToolLabels } from '@/lib/capability-labels';
import type { Capability, SkillDetail, SkillDraft } from '@/lib/types';

import { styles } from './skill-library.styles';

export function SkillView({
  skill,
  tools,
  busy,
  onEdit,
  onCustomize,
  onShare,
  onUse,
}: {
  skill?: SkillDetail;
  tools: Capability[];
  busy: boolean;
  onEdit: () => void;
  onCustomize: () => void;
  onShare: () => void;
  onUse: () => void;
}) {
  if (!skill || busy) return <ActivityIndicator style={styles.loader} color="#007A3D" />;
  const ownershipNote = skill.editable
    ? 'You own this skill. Changes create a new version.'
    : skill.source === 'official'
      ? 'Maintained by FroggyBot. Make an editable copy to change it.'
      : 'Installed from a shared link. Make an editable copy to change it.';

  return (
    <>
      <View style={styles.heroMark}><Text style={styles.heroMarkText}>S</Text></View>
      <Text style={styles.detailName}>{skill.name}</Text>
      <Text style={styles.detailDescription}>{skill.description}</Text>
      <View style={styles.metaRow}>
        <Text style={styles.badge}>{skill.source === 'official' ? 'FroggyBot skill' : skill.editable ? 'Your skill' : 'Shared skill'}</Text>
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
          {requiredToolLabels(skill.requiredToolIds, tools).map((label) => (
            <Text key={label} style={styles.toolPill}>{label}</Text>
          ))}
        </View>
      ) : (
        <Text style={styles.noTools}>None. This skill works from its instructions alone.</Text>
      )}

      <View style={styles.actionRow}>
        <Pressable accessibilityRole="button" style={[styles.button, styles.primaryButton]} onPress={onUse}>
          <Text style={styles.primaryButtonText}>Add to a FroggyBot</Text>
        </Pressable>
        <Pressable accessibilityRole="button" style={[styles.button, styles.secondaryButton]} onPress={skill.editable ? onEdit : onCustomize}>
          <Text style={styles.secondaryButtonText}>{skill.editable ? 'Edit full skill' : 'Make editable copy'}</Text>
        </Pressable>
        <Pressable accessibilityRole="button" style={[styles.button, styles.secondaryButton]} onPress={onShare}>
          <Text style={styles.secondaryButtonText}>Share link</Text>
        </Pressable>
      </View>
    </>
  );
}

export function SkillForm({ draft, tools, onChange }: {
  draft: SkillDraft;
  tools: Capability[];
  onChange: (value: SkillDraft) => void;
}) {
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
