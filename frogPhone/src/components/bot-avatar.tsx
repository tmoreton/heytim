import { Image, StyleSheet, View } from 'react-native';

const frogLogo = require('../../assets/images/frogbot-foreground.png');

type Props = {
  color: string;
  name: string;
  size?: number;
};

export function BotAvatar({ color, name, size = 42 }: Props) {
  const accentSize = Math.max(8, Math.round(size * 0.24));

  return (
    <View accessibilityLabel={`${name} bot`} style={[styles.avatar, { width: size, height: size }]}>
      <Image source={frogLogo} resizeMode="contain" style={{ width: size, height: size }} />
      <View
        style={[
          styles.accent,
          {
            width: accentSize,
            height: accentSize,
            borderRadius: accentSize / 2,
            backgroundColor: color,
            borderWidth: Math.max(1, Math.round(size * 0.045)),
          },
        ]}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  avatar: {
    position: 'relative',
  },
  accent: {
    position: 'absolute',
    right: -1,
    bottom: -1,
    borderColor: '#F2F1ED',
  },
});
