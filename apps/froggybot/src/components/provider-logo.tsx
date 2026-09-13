import {
  Image,
  type ImageSourcePropType,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import type { ConnectionProvider } from '@froggybot/contracts';

const PROVIDER_LOGOS: Readonly<Partial<Record<string, ImageSourcePropType>>> = {
  github: require('../../assets/images/providers/github.png'),
  gmail: require('../../assets/images/providers/gmail.png'),
  google_workspace: require('../../assets/images/providers/google-workspace.png'),
  notion: require('../../assets/images/providers/notion.png'),
  slack: require('../../assets/images/providers/slack.png'),
  x: require('../../assets/images/providers/x.png'),
  youtube: require('../../assets/images/providers/youtube.png'),
};

export function ProviderLogo({ provider }: { provider: ConnectionProvider }) {
  const source = PROVIDER_LOGOS[provider.id];

  return (
    <View
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={styles.shell}>
      {source ? (
        <Image
          accessibilityIgnoresInvertColors
          accessible={false}
          resizeMode="contain"
          source={source}
          style={styles.logo}
        />
      ) : (
        <Text style={styles.fallback}>{provider.iconText}</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  shell: {
    width: 44,
    height: 44,
    borderRadius: 14,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#E2DFD7',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#FFFFFF',
  },
  logo: { width: 32, height: 32 },
  fallback: { color: '#007A3D', fontSize: 18, fontWeight: '900' },
});
