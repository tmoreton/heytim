import { useEffect, useState } from 'react';
import { Animated, Easing, Platform, Pressable, StyleSheet, Text, View } from 'react-native';

import { BotAvatar } from './bot-avatar';

type Props = {
  active: boolean;
  steps: string[];
};

export function AgentActivity({ active, steps }: Props) {
  const [bounce] = useState(() => new Animated.Value(0));
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!active) {
      bounce.setValue(0);
      return;
    }
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(bounce, {
          toValue: 1,
          duration: 520,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: Platform.OS !== 'web',
        }),
        Animated.timing(bounce, {
          toValue: 0,
          duration: 520,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: Platform.OS !== 'web',
        }),
      ]),
    );
    animation.start();
    return () => animation.stop();
  }, [active, bounce]);

  const frogStyle = {
    transform: [
      { translateY: bounce.interpolate({ inputRange: [0, 1], outputRange: [0, -3] }) },
      { rotate: bounce.interpolate({ inputRange: [0, 1], outputRange: ['-3deg', '3deg'] }) },
    ],
  };

  if (active) {
    const latest = steps.at(-1);
    return (
      <View accessibilityLiveRegion="polite" style={styles.activeCard}>
        <Animated.View style={frogStyle}>
          <BotAvatar color="#665CE7" name="Working" size={28} />
        </Animated.View>
        <View style={styles.activeCopy}>
          <Text style={styles.activeLabel}>{latest ? 'Working through it' : 'Thinking'}</Text>
          {latest ? (
            <Text numberOfLines={3} style={styles.activeStep}>
              {latest}
            </Text>
          ) : null}
        </View>
      </View>
    );
  }

  if (!steps.length) return null;

  return (
    <View style={styles.completedWrap}>
      <Pressable
        accessibilityLabel={expanded ? 'Hide FrogBot activity' : 'Show FrogBot activity'}
        accessibilityRole="button"
        accessibilityState={{ expanded }}
        style={({ pressed }) => [styles.completedButton, pressed && styles.pressed]}
        onPress={() => setExpanded((value) => !value)}>
        <BotAvatar color="#665CE7" name="Work log" size={22} />
        <Text style={styles.completedLabel}>{steps.length === 1 ? '1 step completed' : `${steps.length} steps completed`}</Text>
        <Text style={[styles.chevron, expanded && styles.chevronExpanded]}>›</Text>
      </Pressable>
      {expanded ? (
        <View style={styles.stepList}>
          {steps.map((step, index) => (
            <View key={`${index}-${step}`} style={styles.stepRow}>
              <View style={styles.stepDot} />
              <Text style={styles.stepText}>{step}</Text>
            </View>
          ))}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  activeCard: {
    maxWidth: 360,
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#DADDD8',
    backgroundColor: '#F7F8F5',
    paddingHorizontal: 12,
    paddingVertical: 9,
  },
  activeCopy: { flex: 1 },
  activeLabel: { color: '#007A3D', fontSize: 12, fontWeight: '700' },
  activeStep: { color: '#615E57', fontSize: 12, lineHeight: 17, marginTop: 2 },
  completedWrap: { maxWidth: 430, marginBottom: 5 },
  completedButton: {
    minHeight: 34,
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    gap: 7,
    borderRadius: 17,
    backgroundColor: '#F1F4F0',
    paddingLeft: 6,
    paddingRight: 11,
  },
  completedLabel: { color: '#65625B', fontSize: 11, fontWeight: '600' },
  chevron: { color: '#77736B', fontSize: 18, lineHeight: 18, transform: [{ rotate: '0deg' }] },
  chevronExpanded: { transform: [{ rotate: '90deg' }] },
  stepList: {
    gap: 7,
    marginLeft: 12,
    marginTop: 8,
    marginBottom: 4,
    paddingLeft: 10,
    borderLeftWidth: StyleSheet.hairlineWidth,
    borderColor: '#C8CEC8',
  },
  stepRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  stepDot: { width: 5, height: 5, borderRadius: 3, backgroundColor: '#5D9776', marginTop: 6 },
  stepText: { flex: 1, color: '#6A675F', fontSize: 11, lineHeight: 16 },
  pressed: { opacity: 0.65 },
});
