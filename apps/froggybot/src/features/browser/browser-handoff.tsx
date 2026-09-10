import { Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';

import type { BrowserApi } from '@/lib/browser-api';
import type { Bot } from '@/lib/types';

import { BrowserHandoffModal } from './browser-handoff-modal';
import { hasBrowserCapability } from './browser-policy';
import { useBrowserHandoff } from './use-browser-handoff';

type Props = { api: BrowserApi; bot: Bot; active: boolean; visible: boolean;
  initialUrl?: string;
  onOpen: () => void; onClose: () => void; onResumed: () => Promise<void> };

export function BrowserHandoff(props: Props) {
  const { bot, visible, onOpen } = props;
  if (!hasBrowserCapability(bot) && !visible) return null;
  return (
    <View style={styles.row}>
      {hasBrowserCapability(bot) ? <Pressable accessibilityRole="button" onPress={onOpen} style={styles.button}>
        <Text style={styles.label}>Open bot browser</Text>
      </Pressable> : null}
      {visible ? <BrowserDialog {...props} /> : null}
    </View>
  );
}

function BrowserDialog({ api, bot, active, initialUrl, onResumed, onClose }: Props) {
  const { width } = useWindowDimensions();
  const handoff = useBrowserHandoff(api, bot.id, onResumed, onClose,
    { url: initialUrl, display: width < 700 ? 'mobile' : 'desktop' }, !active && hasBrowserCapability(bot));
  return <BrowserHandoffModal botName={bot.name} active={active} canBrowse={hasBrowserCapability(bot)} handoff={handoff} />;
}

const styles = StyleSheet.create({
  row: { paddingHorizontal: 14, paddingVertical: 4, alignItems: 'flex-end' },
  button: { paddingHorizontal: 12, minHeight: 36, justifyContent: 'center', borderRadius: 12, backgroundColor: '#E5F1E9' },
  label: { color: '#007A3D', fontSize: 13, fontWeight: '700' },
});
