import { useState } from 'react';
import { Pressable, SectionList, StyleSheet, Text, TextInput, View } from 'react-native';

import { ActionSheet } from '@/components/action-sheet';
import { BotAvatar } from '@/components/bot-avatar';
import { GroupAvatar } from '@/components/participant-avatar';
import type { Bot, Group } from '@/lib/types';

export type ConversationSelection = { kind: 'bot' | 'group'; id: string };
type DrawerItem = { kind: 'group'; value: Group } | { kind: 'bot'; value: Bot };

type Props = {
  bots: Bot[];
  groups: Group[];
  selection?: ConversationSelection;
  search: string;
  demo: boolean;
  topInset: number;
  bottomInset: number;
  onSearchChange: (value: string) => void;
  onSelectBot: (bot: Bot) => void;
  onSelectGroup: (group: Group) => void;
  onCreateBot: () => void;
  onCreateGroup: () => void;
  onOpenAccount: () => void;
};

const friendlyDate = (value: string) => {
  const date = new Date(value);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) return 'Now';
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
};

export function ConversationDrawer({
  bots,
  groups,
  selection,
  search,
  demo,
  topInset,
  bottomInset,
  onSearchChange,
  onSelectBot,
  onSelectGroup,
  onCreateBot,
  onCreateGroup,
  onOpenAccount,
}: Props) {
  const [createMenuOpen, setCreateMenuOpen] = useState(false);
  const query = search.trim().toLowerCase();
  const visibleBots = bots.filter((bot) => `${bot.name} ${bot.tagline}`.toLowerCase().includes(query));
  const visibleGroups = groups.filter((group) => `${group.name} ${group.lastMessage}`.toLowerCase().includes(query));
  const sections: { title: string; data: DrawerItem[] }[] = [
    { title: 'Groups', data: visibleGroups.map((value) => ({ kind: 'group' as const, value })) },
    { title: 'FroggyBots', data: visibleBots.map((value) => ({ kind: 'bot' as const, value })) },
  ].filter((section) => section.data.length > 0);

  return (
    <View style={styles.drawer}>
      <View style={[styles.top, { minHeight: 70 + topInset, paddingTop: topInset }]}>
        <View>
          <Text style={styles.appName}>FroggyBot</Text>
          <Text style={styles.appTagline}>Your AI team</Text>
        </View>
        <Pressable
          accessibilityLabel="Create bot or group"
          accessibilityRole="button"
          style={({ pressed }) => [styles.addButton, pressed && styles.pressed]}
          onPress={() => setCreateMenuOpen(true)}>
          <Text style={styles.addLabel}>+</Text>
        </Pressable>
      </View>
      <TextInput
        accessibilityLabel="Search chats"
        value={search}
        onChangeText={onSearchChange}
        style={styles.search}
        placeholder="Search chats"
        placeholderTextColor="#9B978F"
        autoCorrect={false}
      />
      <SectionList
        sections={sections}
        keyExtractor={(item) => `${item.kind}-${item.value.id}`}
        contentContainerStyle={styles.list}
        renderSectionHeader={({ section }) => <Text style={styles.sectionLabel}>{section.title}</Text>}
        renderItem={({ item }) => {
          const selected = selection?.kind === item.kind && selection.id === item.value.id;
          return (
            <Pressable
              accessibilityRole="button"
              accessibilityState={{ selected }}
              style={({ pressed }) => [styles.row, selected && styles.rowSelected, pressed && styles.pressed]}
              onPress={() => (item.kind === 'group' ? onSelectGroup(item.value) : onSelectBot(item.value))}>
              {item.kind === 'group' ? (
                <GroupAvatar group={item.value} size={42} />
              ) : (
                <BotAvatar color={item.value.color} name={item.value.name} size={42} />
              )}
              <View style={styles.rowText}>
                <View style={styles.nameRow}>
                  <Text numberOfLines={1} style={styles.name}>
                    {item.value.name}
                  </Text>
                  <Text style={styles.date}>{friendlyDate(item.value.lastMessageAt)}</Text>
                </View>
                <Text numberOfLines={1} style={styles.preview}>
                  {item.value.lastMessage}
                </Text>
              </View>
            </Pressable>
          );
        }}
        ListEmptyComponent={
          <Text style={styles.noResults}>{bots.length || groups.length ? 'No chats match your search.' : 'Loading your chats...'}</Text>
        }
      />
      <View style={[styles.footer, { paddingBottom: bottomInset }]}>
        <Pressable
          accessibilityLabel="Open account settings"
          accessibilityRole="button"
          style={({ pressed }) => [styles.accountRow, pressed && styles.pressed]}
          onPress={onOpenAccount}>
          <View style={styles.profileDot} />
          <View style={styles.profileText}>
            <Text style={styles.profileTitle}>{demo ? 'Preview mode' : 'Your account'}</Text>
            <Text style={styles.profileSubtitle}>{demo ? 'Local sample data' : 'Email code sign-in'}</Text>
          </View>
          <Text style={styles.accountChevron}>›</Text>
        </Pressable>
      </View>
      <ActionSheet
        visible={createMenuOpen}
        title="Create new"
        message="Start a private bot chat or bring people and bots together."
        options={[
          { label: 'New group', onPress: onCreateGroup },
          { label: 'New bot', onPress: onCreateBot },
        ]}
        onClose={() => setCreateMenuOpen(false)}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  drawer: { flex: 1, backgroundColor: '#F2F1ED', borderRightWidth: StyleSheet.hairlineWidth, borderColor: '#D9D6CF' },
  top: { minHeight: 70, paddingHorizontal: 17, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  appName: { color: '#007A3D', fontSize: 20, fontWeight: '800', letterSpacing: -0.5 },
  appTagline: { color: '#8B877F', fontSize: 12, marginTop: 1 },
  addButton: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center', backgroundColor: 'white' },
  addLabel: { color: '#22211D', fontSize: 25, fontWeight: '300', marginTop: -2 },
  search: { height: 44, marginHorizontal: 12, borderRadius: 12, backgroundColor: '#E6E4DF', paddingHorizontal: 13, color: '#1F1E1A', fontSize: 14 },
  list: { padding: 8, paddingTop: 11 },
  sectionLabel: { color: '#8B877F', fontSize: 11, fontWeight: '700', letterSpacing: 0.6, textTransform: 'uppercase', paddingHorizontal: 9, paddingTop: 9, paddingBottom: 5, backgroundColor: '#F2F1ED' },
  noResults: { color: '#858179', fontSize: 13, lineHeight: 19, paddingHorizontal: 14, paddingTop: 24 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 11, minHeight: 64, paddingHorizontal: 9, borderRadius: 13 },
  rowSelected: { backgroundColor: '#E4F1EA' },
  rowText: { flex: 1, minWidth: 0 },
  nameRow: { flexDirection: 'row', alignItems: 'center', gap: 7 },
  name: { flex: 1, color: '#26251F', fontSize: 15, fontWeight: '600' },
  date: { color: '#A09C94', fontSize: 11 },
  preview: { color: '#77736B', fontSize: 12, marginTop: 3 },
  footer: { borderTopWidth: StyleSheet.hairlineWidth, borderColor: '#D9D6CF' },
  accountRow: { minHeight: 64, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, gap: 10 },
  profileDot: { width: 30, height: 30, borderRadius: 15, backgroundColor: '#007A3D' },
  profileText: { flex: 1 },
  profileTitle: { color: '#282722', fontSize: 13, fontWeight: '600' },
  profileSubtitle: { color: '#8B877F', fontSize: 11, marginTop: 1 },
  accountChevron: { color: '#969188', fontSize: 22 },
  pressed: { opacity: 0.7 },
});
