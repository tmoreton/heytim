import { Pressable, StyleSheet, Text, View } from 'react-native';

import { BotAvatar } from '@/components/bot-avatar';
import { GroupAvatar } from '@/components/participant-avatar';
import type { Bot, Group } from '@/lib/types';

type Props = {
  bot?: Bot;
  group?: Group;
  listening: boolean;
  pending: boolean;
  activeBotName?: string;
  waitingBotCount: number;
  topInset: number;
  onToggleDrawer: () => void;
  onEditBot: () => void;
  onEditGroup: () => void;
  onOpenBotMenu: () => void;
};

export function ConversationHeader({
  bot,
  group,
  listening,
  pending,
  activeBotName,
  waitingBotCount,
  topInset,
  onToggleDrawer,
  onEditBot,
  onEditGroup,
  onOpenBotMenu,
}: Props) {
  const status = group
    ? listening
      ? 'Listening...'
      : pending
        ? `${activeBotName ?? 'A FrogBot'} is working${waitingBotCount ? ` · ${waitingBotCount} waiting` : ''}`
        : `${group.members.length} people · ${group.bots.length} bots`
    : listening
      ? 'Listening...'
      : pending
        ? 'Working...'
        : 'Ready';

  return (
    <View style={[styles.header, { minHeight: 58 + topInset, paddingTop: topInset }]}>
      <Pressable
        accessibilityLabel="Toggle chat list"
        accessibilityRole="button"
        hitSlop={12}
        style={styles.menuButton}
        onPress={onToggleDrawer}>
        <View style={styles.menuLine} />
        <View style={[styles.menuLine, styles.menuLineShort]} />
      </Pressable>
      {group ? (
        <>
          <GroupAvatar group={group} size={34} />
          <Identity name={group.name} status={status} />
          <HeaderAction label="Details" onPress={onEditGroup} />
        </>
      ) : bot ? (
        <>
          <BotAvatar color={bot.color} name={bot.name} size={31} />
          <Identity name={bot.name} status={status} />
          <HeaderAction label="Edit" onPress={onEditBot} />
          <Pressable
            accessibilityLabel={`${bot.name} actions`}
            accessibilityRole="button"
            style={styles.moreButton}
            hitSlop={10}
            onPress={onOpenBotMenu}>
            <Text style={styles.moreLabel}>...</Text>
          </Pressable>
        </>
      ) : null}
    </View>
  );
}

function Identity({ name, status }: { name: string; status: string }) {
  return (
    <View style={styles.identity}>
      <Text numberOfLines={1} style={styles.name}>
        {name}
      </Text>
      <Text numberOfLines={1} style={styles.status}>
        {status}
      </Text>
    </View>
  );
}

function HeaderAction({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" style={styles.action} hitSlop={10} onPress={onPress}>
      <Text style={styles.actionLabel}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  header: {
    minHeight: 58,
    paddingHorizontal: 14,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 9,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderColor: '#E0DED8',
  },
  menuButton: { width: 32, height: 32, justifyContent: 'center', gap: 5 },
  menuLine: { width: 19, height: 2, backgroundColor: '#383731', borderRadius: 2 },
  menuLineShort: { width: 13 },
  identity: { flex: 1, minWidth: 0 },
  name: { color: '#22211E', fontSize: 15, fontWeight: '700' },
  status: { color: '#007A3D', fontSize: 11, marginTop: 1 },
  action: { paddingHorizontal: 7, paddingVertical: 7 },
  actionLabel: { color: '#5B5851', fontSize: 13, fontWeight: '600' },
  moreButton: { width: 32, height: 32, justifyContent: 'center', alignItems: 'center' },
  moreLabel: { color: '#4B4942', fontSize: 19, letterSpacing: 1, marginTop: -7 },
});
