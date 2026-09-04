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
import type { Bot, BotDraft, Capability } from '@/lib/types';

const COLORS = ['#007A3D', '#FFAA34', '#6C5CE7', '#3984F6', '#F46A27', '#E95383'];

const emptyDraft: BotDraft = {
  name: '',
  tagline: '',
  prompt: '',
  color: COLORS[0],
  toolIds: [],
  skillIds: [],
};

type Props = {
  bot?: Bot;
  tools: Capability[];
  skills: Capability[];
  onClose: () => void;
  onSave: (draft: BotDraft) => Promise<void>;
};

export function BotEditor({ bot, tools, skills, onClose, onSave }: Props) {
  const [draft, setDraft] = useState<BotDraft>(() =>
    bot
      ? {
          name: bot.name,
          tagline: bot.tagline,
          prompt: bot.prompt,
          color: bot.color,
          toolIds: bot.toolIds,
          skillIds: bot.skillIds,
        }
      : emptyDraft,
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const toggle = (field: 'toolIds' | 'skillIds', id: string) => {
    setDraft((current) => ({
      ...current,
      [field]: current[field].includes(id) ? current[field].filter((value) => value !== id) : [...current[field], id],
    }));
  };

  const save = async () => {
    if (!draft.name.trim() || !draft.prompt.trim()) {
      setError('Give your bot a name and a role.');
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
          <Pressable hitSlop={12} onPress={onClose}>
            <Text style={styles.headerAction}>Cancel</Text>
          </Pressable>
          <Text style={styles.title}>{bot ? 'Edit bot' : 'New bot'}</Text>
          <Pressable hitSlop={12} disabled={saving} onPress={save}>
            {saving ? <ActivityIndicator color="#007A3D" /> : <Text style={[styles.headerAction, styles.save]}>Save</Text>}
          </Pressable>
        </View>

        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <View style={styles.identity}>
            <BotAvatar name={draft.name || 'New bot'} color={draft.color} size={64} />
            <View style={styles.identityText}>
              <TextInput
                style={styles.nameInput}
                value={draft.name}
                onChangeText={(name) => setDraft((value) => ({ ...value, name }))}
                placeholder="Bot name"
                placeholderTextColor="#A4A098"
                maxLength={48}
              />
              <TextInput
                style={styles.taglineInput}
                value={draft.tagline}
                onChangeText={(tagline) => setDraft((value) => ({ ...value, tagline }))}
                placeholder="One-line description"
                placeholderTextColor="#A4A098"
                maxLength={120}
              />
            </View>
          </View>

          <Text style={styles.label}>Color</Text>
          <View style={styles.colorRow}>
            {COLORS.map((color) => (
              <Pressable
                key={color}
                accessibilityLabel={`Use color ${color}`}
                style={[styles.color, { backgroundColor: color }, draft.color === color && styles.colorSelected]}
                onPress={() => setDraft((value) => ({ ...value, color }))}
              />
            ))}
          </View>

          <Text style={styles.label}>Role and instructions</Text>
          <TextInput
            style={styles.promptInput}
            value={draft.prompt}
            onChangeText={(prompt) => setDraft((value) => ({ ...value, prompt }))}
            placeholder="What should this bot be great at? How should it work with you?"
            placeholderTextColor="#A4A098"
            multiline
            textAlignVertical="top"
            maxLength={12000}
          />

          <CapabilitySection
            title="Tools"
            subtitle="Actions this bot can take"
            items={tools}
            selected={draft.toolIds}
            onToggle={(id) => toggle('toolIds', id)}
          />
          <CapabilitySection
            title="Skills"
            subtitle="Ways this bot knows how to work"
            items={skills}
            selected={draft.skillIds}
            onToggle={(id) => toggle('skillIds', id)}
          />
          {error ? <Text style={styles.error}>{error}</Text> : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function CapabilitySection({
  title,
  subtitle,
  items,
  selected,
  onToggle,
}: {
  title: string;
  subtitle: string;
  items: Capability[];
  selected: string[];
  onToggle: (id: string) => void;
}) {
  return (
    <View style={styles.section}>
      <Text style={styles.label}>{title}</Text>
      <Text style={styles.sectionSubtitle}>{subtitle}</Text>
      {items.map((item) => {
        const active = selected.includes(item.id);
        return (
          <Pressable key={item.id} style={[styles.capability, active && styles.capabilityActive]} onPress={() => onToggle(item.id)}>
            <View style={[styles.check, active && styles.checkActive]}>{active ? <Text style={styles.checkMark}>✓</Text> : null}</View>
            <View style={styles.capabilityText}>
              <Text style={styles.capabilityName}>{item.name}</Text>
              <Text style={styles.capabilityDescription}>{item.description}</Text>
            </View>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: '#F8F7F3' },
  header: {
    minHeight: 58,
    paddingHorizontal: 18,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderColor: '#DDDAD2',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: 'white',
  },
  title: { fontSize: 16, fontWeight: '700', color: '#171714' },
  headerAction: { color: '#5D5A54', fontSize: 16 },
  save: { color: '#007A3D', fontWeight: '700' },
  content: { padding: 20, paddingBottom: 60, maxWidth: 680, width: '100%', alignSelf: 'center' },
  identity: { flexDirection: 'row', alignItems: 'center', gap: 15, marginBottom: 26 },
  identityText: { flex: 1, gap: 7 },
  nameInput: { fontSize: 23, fontWeight: '700', color: '#171714', padding: 0 },
  taglineInput: { fontSize: 14, color: '#716E67', padding: 0 },
  label: { fontSize: 14, fontWeight: '700', color: '#24231F', marginBottom: 8 },
  colorRow: { flexDirection: 'row', gap: 12, marginBottom: 26 },
  color: { width: 32, height: 32, borderRadius: 16, borderWidth: 3, borderColor: '#F8F7F3' },
  colorSelected: { borderColor: '#007A3D' },
  promptInput: {
    minHeight: 148,
    padding: 15,
    borderRadius: 15,
    borderWidth: 1,
    borderColor: '#DDDAD2',
    backgroundColor: 'white',
    color: '#24231F',
    fontSize: 15,
    lineHeight: 21,
  },
  section: { marginTop: 26 },
  sectionSubtitle: { color: '#858179', fontSize: 13, marginTop: -4, marginBottom: 10 },
  capability: {
    flexDirection: 'row',
    gap: 12,
    alignItems: 'center',
    padding: 13,
    borderRadius: 14,
    marginBottom: 8,
    backgroundColor: 'white',
    borderWidth: 1,
    borderColor: '#E4E1DA',
  },
  capabilityActive: { borderColor: '#8AB99F', backgroundColor: '#EAF5EF' },
  check: { width: 22, height: 22, borderRadius: 7, borderWidth: 1, borderColor: '#C9C5BD', alignItems: 'center' },
  checkActive: { backgroundColor: '#007A3D', borderColor: '#007A3D' },
  checkMark: { color: 'white', fontSize: 14, fontWeight: '800' },
  capabilityText: { flex: 1 },
  capabilityName: { fontSize: 15, color: '#24231F', fontWeight: '600' },
  capabilityDescription: { fontSize: 13, color: '#858179', marginTop: 2 },
  error: { color: '#B83C32', marginTop: 16 },
});
