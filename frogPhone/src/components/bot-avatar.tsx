import { Image, Platform, StyleSheet, View } from 'react-native';

const frogLogo = require('../../assets/images/frogbot-foreground.png');

type Props = {
  color: string;
  name: string;
  size?: number;
};

export function BotAvatar({ color, name, size = 42 }: Props) {
  const featureRadius = Math.max(2, size * 0.1);

  return (
    <View
      accessible
      accessibilityLabel={`${name} bot`}
      accessibilityRole="image"
      style={[styles.avatar, { width: size, height: size }]}>
      <Image
        accessibilityIgnoresInvertColors
        source={frogLogo}
        resizeMode="contain"
        {...(Platform.OS === 'web' ? { tintColor: color } : {})}
        style={[styles.frog, Platform.OS !== 'web' && { tintColor: color }]}
      />
      <View style={styles.features}>
        <View style={[styles.eye, styles.leftEye, { borderRadius: featureRadius }]}>
          <View style={[styles.pupil, { backgroundColor: color, borderRadius: featureRadius }]}>
            <View style={[styles.eyeGlint, { borderRadius: featureRadius }]} />
          </View>
        </View>
        <View style={[styles.eye, styles.rightEye, { borderRadius: featureRadius }]}>
          <View style={[styles.pupil, { backgroundColor: color, borderRadius: featureRadius }]}>
            <View style={[styles.eyeGlint, { borderRadius: featureRadius }]} />
          </View>
        </View>
        <View
          style={[
            styles.smile,
            {
              borderBottomWidth: Math.max(2, size * 0.057),
              borderRadius: featureRadius,
            },
          ]}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  avatar: {
    position: 'relative',
  },
  frog: {
    width: '100%',
    height: '100%',
  },
  features: {
    position: 'absolute',
    inset: 0,
    pointerEvents: 'none',
  },
  eye: {
    position: 'absolute',
    top: '25.3%',
    width: '19%',
    height: '19%',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#FFFFFF',
  },
  leftEye: {
    left: '20%',
  },
  rightEye: {
    right: '20%',
  },
  pupil: {
    width: '44%',
    height: '44%',
  },
  eyeGlint: {
    position: 'absolute',
    top: '12%',
    right: '12%',
    width: '35%',
    height: '35%',
    backgroundColor: '#FFFFFF',
  },
  smile: {
    position: 'absolute',
    top: '56.5%',
    left: '36.5%',
    width: '27%',
    height: '12%',
    borderBottomColor: '#FFFFFF',
  },
});
