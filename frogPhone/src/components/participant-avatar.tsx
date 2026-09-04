import { StyleSheet, Text, View } from 'react-native';

import type { Group } from '@/lib/types';

import { BotAvatar } from './bot-avatar';

const PERSON_COLORS = ['#2F6FA3', '#7A52A3', '#B85D3B', '#436F5A', '#9A6A24'];

function personColor(name: string) {
  const sum = Array.from(name).reduce((total, character) => total + character.charCodeAt(0), 0);
  return PERSON_COLORS[sum % PERSON_COLORS.length];
}

export function PersonAvatar({ name, size = 34 }: { name: string; size?: number }) {
  const initial = name.trim().charAt(0).toUpperCase() || 'P';
  return (
    <View
      accessibilityLabel={`${name}, person`}
      style={[styles.person, { width: size, height: size, borderRadius: size / 2, backgroundColor: personColor(name) }]}>
      <Text style={[styles.initial, { fontSize: Math.max(11, Math.round(size * 0.4)) }]}>{initial}</Text>
    </View>
  );
}

export function GroupAvatar({ group, size = 44 }: { group: Group; size?: number }) {
  const tileSize = Math.round(size * 0.7);
  const firstBot = group.bots[0];
  const secondBot = group.bots[1];
  const firstPerson = group.members[0];

  return (
    <View accessibilityLabel={`${group.name} group`} style={{ width: size, height: size }}>
      <View style={styles.backTile}>
        {secondBot ? (
          <BotAvatar name={secondBot.name} color={secondBot.color} size={tileSize} />
        ) : (
          <PersonAvatar name={firstPerson?.name ?? group.name} size={tileSize} />
        )}
      </View>
      <View style={styles.frontTile}>
        {firstBot ? (
          <BotAvatar name={firstBot.name} color={firstBot.color} size={tileSize} />
        ) : (
          <PersonAvatar name={firstPerson?.name ?? group.name} size={tileSize} />
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  person: { alignItems: 'center', justifyContent: 'center' },
  initial: { color: 'white', fontWeight: '800' },
  backTile: { position: 'absolute', right: 0, top: 0 },
  frontTile: {
    position: 'absolute',
    left: 0,
    bottom: 0,
    borderWidth: 2,
    borderColor: '#FBFBF9',
    borderRadius: 999,
  },
});
