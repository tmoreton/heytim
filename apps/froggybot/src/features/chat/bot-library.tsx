import { useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { BotAvatar } from '@/components/bot-avatar';
import { PageSheet } from '@/components/page-sheet';
import type { Bot, BotTemplate, Skill } from '@/lib/types';

type Props = {
  bots: Bot[];
  templates: BotTemplate[];
  skills: Skill[];
  onboarding: boolean;
  initialTemplateId?: string;
  onClose: () => void;
  onInstall: (templateId: string) => Promise<Bot>;
};

const countLabel = (count: number, singular: string) =>
  `${count} ${count === 1 ? singular : `${singular}s`}`;

export function BotLibrary({
  bots,
  templates,
  skills,
  onboarding,
  initialTemplateId,
  onClose,
  onInstall,
}: Props) {
  const [installingId, setInstallingId] = useState<string>();
  const [error, setError] = useState('');
  const installedIds = useMemo(
    () => new Set(bots.flatMap((bot) => (bot.templateId ? [bot.templateId] : []))),
    [bots],
  );
  const toolsBySkill = useMemo(
    () => new Map(skills.map((skill) => [skill.id, skill.requiredToolIds])),
    [skills],
  );
  const orderedTemplates = useMemo(
    () => [...templates].sort((left, right) => {
      if (left.id === initialTemplateId) return -1;
      if (right.id === initialTemplateId) return 1;
      return Number(Boolean(right.featured)) - Number(Boolean(left.featured)) || left.name.localeCompare(right.name);
    }),
    [initialTemplateId, templates],
  );

  const install = async (template: BotTemplate) => {
    setInstallingId(template.id);
    setError('');
    try {
      await onInstall(template.id);
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not add this bot.');
    } finally {
      setInstallingId(undefined);
    }
  };

  return (
    <PageSheet onClose={onClose}>
      <View style={styles.page}>
        <View style={styles.header}>
          <View style={styles.headerSpacer} />
          <Text accessibilityRole="header" numberOfLines={1} style={styles.title}>
            {onboarding ? 'Build your team' : 'Bot library'}
          </Text>
          <Pressable accessibilityRole="button" hitSlop={12} onPress={onClose}>
            <Text style={styles.done}>Done</Text>
          </Pressable>
        </View>
        <ScrollView contentContainerStyle={styles.content}>
          <View style={styles.intro}>
            <Text style={styles.introTitle}>
              {onboarding ? 'Chief is ready. Add the specialists you want.' : 'Add a ready-to-work specialist.'}
            </Text>
            <Text style={styles.introText}>
              Each bot is a reviewed prompt with skills and required tools. You can edit your copy after adding it.
            </Text>
          </View>

          {orderedTemplates.map((template) => {
            const effectiveToolIds = new Set([
              ...template.toolIds,
              ...template.skillIds.flatMap((skillId) => toolsBySkill.get(skillId) ?? []),
            ]);
            const installed = installedIds.has(template.id);
            const busy = installingId === template.id;
            const disabled = installed || Boolean(installingId);
            return (
              <View key={template.id} style={[styles.card, template.id === initialTemplateId && styles.highlightedCard]}>
                <BotAvatar color={template.color} name={template.name} size={48} />
                <View style={styles.cardBody}>
                  <View style={styles.nameRow}>
                    <Text style={styles.name}>{template.name}</Text>
                    {template.featured ? <Text style={styles.badge}>Featured</Text> : null}
                  </View>
                  <Text style={styles.tagline}>{template.tagline}</Text>
                  <Text style={styles.meta}>
                    {template.skillIds.length
                      ? countLabel(template.skillIds.length, 'skill')
                      : 'Prompt only'}
                    {effectiveToolIds.size ? ` · ${countLabel(effectiveToolIds.size, 'required tool')}` : ''}
                  </Text>
                </View>
                <Pressable
                  accessibilityLabel={installed ? `${template.name} is added` : `Add ${template.name}`}
                  accessibilityRole="button"
                  accessibilityState={{ busy, disabled }}
                  disabled={disabled}
                  style={({ pressed }) => [
                    styles.addButton,
                    installed && styles.addedButton,
                    pressed && styles.pressed,
                  ]}
                  onPress={() => void install(template)}>
                  {busy ? (
                    <ActivityIndicator color="#FFFFFF" size="small" />
                  ) : (
                    <Text style={[styles.addText, installed && styles.addedText]}>
                      {installed ? 'Added' : 'Add'}
                    </Text>
                  )}
                </Pressable>
              </View>
            );
          })}
          {orderedTemplates.length === 0 ? (
            <Text style={styles.empty}>The bot library is unavailable right now. Chief is still ready to help.</Text>
          ) : null}
          <View style={styles.credentialNote}>
            <Text style={styles.credentialTitle}>When a private tool needs an API token</Text>
            <Text style={styles.credentialText}>
              Open Skills & tools, choose Tools → Add tool, select Bearer token or API key, and paste the token there.
              Tokens are encrypted and never included in bot configs or shared links.
            </Text>
          </View>
          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
        </ScrollView>
      </View>
    </PageSheet>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: '#F8F7F3' },
  header: { minHeight: 58, paddingHorizontal: 18, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: '#DDDAD2', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: '#FBFBF9' },
  headerSpacer: { width: 42 },
  title: { maxWidth: '66%', fontSize: 16, fontWeight: '700', color: '#171714' },
  done: { color: '#007A3D', fontSize: 15, fontWeight: '700' },
  content: { padding: 20, paddingBottom: 60, maxWidth: 720, width: '100%', alignSelf: 'center' },
  intro: { padding: 18, borderRadius: 18, backgroundColor: '#E9F4EE', marginBottom: 18 },
  introTitle: { color: '#173E2A', fontSize: 18, lineHeight: 24, fontWeight: '800' },
  introText: { color: '#587363', fontSize: 13, lineHeight: 19, marginTop: 5 },
  card: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, marginBottom: 10, borderRadius: 17, borderWidth: 1, borderColor: '#E2DFD7', backgroundColor: '#FFFFFF' },
  highlightedCard: { borderColor: '#78AE8E', backgroundColor: '#FBFFFC' },
  cardBody: { flex: 1, minWidth: 0 },
  nameRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 7 },
  name: { flexShrink: 1, color: '#24231F', fontSize: 15, fontWeight: '800' },
  badge: { color: '#007A3D', backgroundColor: '#E4F1EA', overflow: 'hidden', borderRadius: 8, paddingHorizontal: 7, paddingVertical: 3, fontSize: 10, fontWeight: '700' },
  tagline: { color: '#6F6B64', fontSize: 12, lineHeight: 17, marginTop: 4 },
  meta: { color: '#918D84', fontSize: 10.5, lineHeight: 15, marginTop: 5 },
  addButton: { minWidth: 62, minHeight: 38, borderRadius: 12, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 12, backgroundColor: '#007A3D' },
  addedButton: { backgroundColor: '#E4F1EA' },
  addText: { color: '#FFFFFF', fontSize: 13, fontWeight: '800' },
  addedText: { color: '#007A3D' },
  credentialNote: { padding: 16, borderRadius: 16, backgroundColor: '#EFEEE9', marginTop: 12 },
  credentialTitle: { color: '#37352F', fontSize: 13, fontWeight: '800' },
  credentialText: { color: '#77736B', fontSize: 12, lineHeight: 18, marginTop: 4 },
  empty: { color: '#77736B', fontSize: 13, lineHeight: 19, paddingVertical: 28, textAlign: 'center' },
  error: { color: '#A43C31', fontSize: 13, lineHeight: 18, marginTop: 16 },
  pressed: { opacity: 0.7 },
});
