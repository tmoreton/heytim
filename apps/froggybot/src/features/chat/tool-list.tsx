import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { Capability, CapabilitySelection, Connection } from '@/lib/types';

const providerLabel = (provider?: string) => {
  if (provider === 'stan') return 'Stan';
  if (provider === 'agentcore') return 'AgentCore';
  if (provider === 'agentcore-gateway') return 'Connected service';
  if (provider === 'mcp') return 'Private MCP';
  if (provider === 'gmail') return 'Google';
  return 'FroggyBot';
};

const isConnection = (tool: Capability): tool is Connection =>
  tool.source === 'user' && tool.editable === true && typeof (tool as Connection).endpoint === 'string';

export function HowCapabilitiesWork() {
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

export function ToolList({
  tools,
  onUse,
  onManage,
  onConnectGmail,
}: {
  tools: Capability[];
  onUse: (capability: CapabilitySelection) => void;
  onManage: (connection: Connection) => void;
  onConnectGmail: () => void;
}) {
  const gmailConnected = tools.some((tool) => tool.provider === 'gmail');
  return (
    <>
      <Text style={styles.sectionLabel}>Tools and connections</Text>
      <Text style={styles.listHelp}>
        Add a private MCP connection without publishing it. A bot receives only the tools you choose.
      </Text>
      {!gmailConnected ? (
        <Pressable
          accessibilityRole="button"
          style={({ pressed }) => [styles.gmailCard, pressed && styles.pressed]}
          onPress={onConnectGmail}>
          <View style={styles.gmailMark}><Text style={styles.gmailMarkText}>G</Text></View>
          <View style={styles.cardText}>
            <Text style={styles.toolName}>Connect Gmail</Text>
            <Text style={styles.description}>Search and summarize email, then create drafts for review.</Text>
            <Text style={styles.gmailMeta}>No sending, deleting, or relabeling</Text>
          </View>
          <Text style={styles.chevron}>›</Text>
        </Pressable>
      ) : null}
      {tools.map((tool) => {
        const connection = isConnection(tool);
        return (
          <Pressable
            accessibilityRole="button"
            key={tool.id}
            style={({ pressed }) => [styles.card, pressed && styles.pressed]}
            onPress={() => connection ? onManage(tool) : onUse({ kind: 'tool', id: tool.id })}>
            <View style={styles.toolMark}><Text style={styles.toolMarkText}>T</Text></View>
            <View style={styles.cardText}>
              <View style={styles.nameRow}>
                <Text style={styles.toolName}>{tool.name}</Text>
                <Text style={styles.badge}>{providerLabel(tool.provider)}</Text>
              </View>
              <Text style={styles.description}>{tool.description}</Text>
              <Text style={styles.meta}>
                {connection
                  ? `${tool.connectedAccount ? `${tool.connectedAccount} · ` : 'Private · '}tap to manage`
                  : 'Tap to add this tool to a FroggyBot'}
              </Text>
            </View>
            <Text style={styles.chevron}>›</Text>
          </Pressable>
        );
      })}
    </>
  );
}

const styles = StyleSheet.create({
  guide: { padding: 17, borderRadius: 18, backgroundColor: '#E9F4EE', borderWidth: 1, borderColor: '#CBE2D5' },
  guideTitle: { color: '#173E2A', fontSize: 16, fontWeight: '800', marginBottom: 8 },
  guideLine: { color: '#527060', fontSize: 13, lineHeight: 20 },
  guideStrong: { color: '#173E2A', fontWeight: '800' },
  guideNote: { color: '#007A3D', fontSize: 12, fontWeight: '700', marginTop: 9 },
  sectionLabel: { color: '#24231F', fontSize: 13, fontWeight: '800', marginTop: 26, marginBottom: 10, textTransform: 'uppercase', letterSpacing: 0.7 },
  listHelp: { color: '#7B776F', fontSize: 13, lineHeight: 19, marginTop: -4, marginBottom: 12 },
  card: { minHeight: 76, flexDirection: 'row', alignItems: 'center', gap: 12, padding: 13, marginBottom: 9, borderRadius: 16, borderWidth: 1, borderColor: '#E2DFD7', backgroundColor: '#FFFFFF' },
  gmailCard: { minHeight: 84, flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, marginBottom: 12, borderRadius: 17, borderWidth: 1, borderColor: '#CBE2D5', backgroundColor: '#F3FAF6' },
  gmailMark: { width: 44, height: 44, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: '#DCEFE4' },
  gmailMarkText: { color: '#007A3D', fontSize: 18, fontWeight: '900' },
  gmailMeta: { color: '#007A3D', fontSize: 11, fontWeight: '700', marginTop: 5 },
  toolMark: { width: 42, height: 42, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: '#EFEEE9' },
  toolMarkText: { color: '#57534C', fontSize: 17, fontWeight: '900' },
  cardText: { flex: 1, minWidth: 0 },
  nameRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8 },
  toolName: { flexShrink: 1, color: '#24231F', fontSize: 15, fontWeight: '700' },
  description: { color: '#7B776F', fontSize: 12, lineHeight: 17, marginTop: 4 },
  meta: { color: '#9A968D', fontSize: 11, marginTop: 5 },
  badge: { color: '#625E57', backgroundColor: '#EFEEE9', fontSize: 10, fontWeight: '700', paddingHorizontal: 7, paddingVertical: 3, borderRadius: 8, overflow: 'hidden' },
  chevron: { color: '#A39F97', fontSize: 25, fontWeight: '300' },
  pressed: { opacity: 0.7 },
});
