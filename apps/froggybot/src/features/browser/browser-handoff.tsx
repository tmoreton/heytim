import { useWindowDimensions } from 'react-native';

import type { BrowserApi } from '@froggybot/client';
import type { Bot } from '@froggybot/contracts';

import { BrowserHandoffModal } from './browser-handoff-modal';
import { hasBrowserCapability } from '@froggybot/client';
import { useBrowserHandoff } from '@froggybot/expo-client/use-browser-handoff';

type Props = { api: BrowserApi; bot: Bot; active: boolean; visible: boolean;
  initialUrl?: string;
  onClose: () => void; onResumed: () => Promise<void> };

export function BrowserHandoff(props: Props) {
  // Chat links and the existing bot-actions menu own the entry points. No
  // persistent button or empty spacer should take space from the conversation.
  return props.visible ? <BrowserDialog {...props} /> : null;
}

function BrowserDialog({ api, bot, active, initialUrl, onResumed, onClose }: Props) {
  const { width } = useWindowDimensions();
  const handoff = useBrowserHandoff(api, bot.id, onResumed, onClose,
    { url: initialUrl, display: width < 700 ? 'mobile' : 'desktop' }, !active && hasBrowserCapability(bot));
  return <BrowserHandoffModal botName={bot.name} active={active} canBrowse={hasBrowserCapability(bot)} handoff={handoff} />;
}
