import { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  Share,
  Text,
  View,
} from 'react-native';

import type { Capability, CapabilitySelection, Skill, SkillDetail, SkillDraft } from '@/lib/types';
import { PageSheet } from '@/components/page-sheet';

import { catalogTools } from './connection-access';
import { SkillForm, SkillView } from './skill-details';
import { styles } from './skill-library.styles';
import { HowCapabilitiesWork, ToolList } from './tool-list';

const emptyDraft: SkillDraft = {
  name: '',
  description: '',
  instructions: '',
  requiredToolIds: [],
  visibility: 'private',
};

type LibraryTab = 'skills' | 'tools';
type LibraryMode = 'list' | 'view' | 'edit' | 'copy' | 'new';

type Props = {
  skills: Skill[];
  tools: Capability[];
  onClose: () => void;
  onLoad: (skillId: string) => Promise<SkillDetail>;
  onSave: (draft: SkillDraft, skillId?: string) => Promise<SkillDetail>;
  onShare: (skillId: string) => Promise<string>;
  onChanged: () => Promise<void>;
  onUse: (capability: CapabilitySelection) => void;
};

export function SkillLibrary({
  skills,
  tools,
  onClose,
  onLoad,
  onSave,
  onShare,
  onChanged,
  onUse,
}: Props) {
  const [selected, setSelected] = useState<SkillDetail>();
  const [draft, setDraft] = useState<SkillDraft>(emptyDraft);
  const [mode, setMode] = useState<LibraryMode>('list');
  const [tab, setTab] = useState<LibraryTab>('skills');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const includedTools = catalogTools(tools);

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
        message: `Add the ${selected.name} skill to FroggyBot: ${url}`,
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
    setMode(selected ? 'view' : 'list');
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
    <PageSheet accessibilityLabel="Skills and tools" onClose={onClose}>
      <KeyboardAvoidingView style={styles.page} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.header}>
          <Pressable accessibilityRole="button" hitSlop={12} onPress={mode === 'list' ? onClose : back}>
            <Text style={styles.headerAction}>{mode === 'list' ? 'Close' : 'Back'}</Text>
          </Pressable>
          <Text numberOfLines={1} style={styles.title}>{title}</Text>
          {mode === 'list' && tab === 'skills' ? (
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
              <HowCapabilitiesWork />
              <View accessibilityRole="tablist" style={styles.tabs}>
                {(['skills', 'tools'] as const).map((value) => (
                  <Pressable
                    key={value}
                    accessibilityRole="tab"
                    accessibilityState={{ selected: tab === value }}
                    aria-selected={tab === value}
                    style={[styles.tab, tab === value && styles.tabActive]}
                    onPress={() => setTab(value)}>
                    <Text style={[styles.tabText, tab === value && styles.tabTextActive]}>
                      {value === 'skills' ? `Skills · ${skills.length}` : `Tools · ${includedTools.length}`}
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
                            {skill.source === 'official' ? 'FroggyBot' : skill.relationship === 'owner' ? 'Yours' : 'Shared'}
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
                <ToolList tools={includedTools} onUse={onUse} />
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
              onUse={() => onUse({ kind: 'skill', id: selected?.id ?? '' })}
            />
          ) : (
            <SkillForm draft={draft} tools={tools} onChange={setDraft} />
          )}
          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </PageSheet>
  );
}
