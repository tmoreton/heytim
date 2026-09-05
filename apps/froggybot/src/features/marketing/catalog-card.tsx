import { Link, type Href } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { Capability, Skill } from '@/lib/types';

type Props = {
  item: Capability | Skill;
  kind: 'skill' | 'tool';
};

const isSkill = (item: Capability | Skill): item is Skill => 'requiredToolIds' in item;

const riskLabel = (risk?: Capability['risk']) => {
  if (risk === 'interactive') return 'Approval before actions';
  if (risk === 'sandbox') return 'Runs in a sandbox';
  if (risk === 'read') return 'Read-only or local';
  return 'Access details pending review';
};

export function CatalogCard({ item, kind }: Props) {
  const details = isSkill(item)
    ? item.requiredToolIds.length
      ? [`Uses ${item.requiredToolIds.length} ${item.requiredToolIds.length === 1 ? 'tool' : 'tools'}`]
      : ['Instructions only']
    : item.actions?.slice(0, 3) ?? [];
  const href = (kind === 'skill' ? `/app?skill=${encodeURIComponent(item.id)}` : `/app?tool=${encodeURIComponent(item.id)}`) as Href;

  return (
    <View style={styles.card}>
      <View style={styles.topRow}>
        <View style={[styles.mark, kind === 'tool' && styles.toolMark]}>
          <Text style={[styles.markText, kind === 'tool' && styles.toolMarkText]}>{kind === 'skill' ? 'S' : 'T'}</Text>
        </View>
        <View style={styles.badges}>
          {item.featured ? <Text style={styles.featured}>Featured</Text> : null}
          <Text style={styles.category}>{item.category ?? 'General'}</Text>
        </View>
      </View>
      <Text accessibilityRole="header" style={styles.name}>{item.name}</Text>
      <Text style={styles.description}>{item.description}</Text>
      <Text style={styles.author}>Reviewed · {item.author ?? 'FroggyBot'}</Text>
      <View style={styles.details}>
        {(details.length ? details : [riskLabel(item.risk)]).map((detail) => (
          <Text key={detail} style={styles.detail}>{detail}</Text>
        ))}
      </View>
      {kind === 'tool' ? <Text style={styles.safety}>{riskLabel(item.risk)}</Text> : null}
      <Link href={href} asChild>
        <Pressable accessibilityRole="link" style={({ pressed }) => [styles.button, pressed && styles.pressed]}>
          <Text style={styles.buttonText}>Add to a FroggyBot</Text>
          <Text style={styles.arrow}>→</Text>
        </Pressable>
      </Link>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { flexGrow: 1, flexBasis: 300, maxWidth: 390, minHeight: 310, padding: 22, borderRadius: 22, borderWidth: 1, borderColor: '#DDD9CF', backgroundColor: '#FFFFFF' },
  topRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 12 },
  mark: { width: 44, height: 44, borderRadius: 14, backgroundColor: '#E1F0E8', alignItems: 'center', justifyContent: 'center' },
  toolMark: { backgroundColor: '#EEECE6' },
  markText: { color: '#007A3D', fontSize: 18, fontWeight: '900' },
  toolMarkText: { color: '#5E5A52' },
  badges: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'flex-end', gap: 6 },
  featured: { color: '#075A31', backgroundColor: '#E1F0E8', borderRadius: 10, overflow: 'hidden', paddingHorizontal: 9, paddingVertical: 5, fontSize: 10, fontWeight: '800' },
  category: { color: '#666159', backgroundColor: '#F0EEE8', borderRadius: 10, overflow: 'hidden', paddingHorizontal: 9, paddingVertical: 5, fontSize: 10, fontWeight: '700' },
  name: { color: '#181713', fontSize: 22, fontWeight: '800', letterSpacing: -0.4, marginTop: 20 },
  description: { color: '#6E6960', fontSize: 14, lineHeight: 21, marginTop: 8, minHeight: 42 },
  author: { color: '#948F85', fontSize: 11, marginTop: 12 },
  details: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 18 },
  detail: { color: '#4E6658', backgroundColor: '#EEF5F1', borderRadius: 10, overflow: 'hidden', paddingHorizontal: 9, paddingVertical: 6, fontSize: 11, fontWeight: '600' },
  safety: { color: '#8A857C', fontSize: 11, marginTop: 9 },
  button: { marginTop: 'auto', minHeight: 46, paddingHorizontal: 15, borderRadius: 14, backgroundColor: '#007A3D', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  buttonText: { color: '#FFFFFF', fontSize: 13, fontWeight: '800' },
  arrow: { color: '#FFFFFF', fontSize: 18 },
  pressed: { opacity: 0.72 },
});
