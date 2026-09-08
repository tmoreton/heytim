import { useLocalSearchParams } from 'expo-router';

import { AppEntry } from '@/features/app/app-entry';
import type { CapabilitySelection } from '@/lib/types';

const param = (value?: string | string[]) => Array.isArray(value) ? value[0] : value;

export default function AppPage() {
  const { bot, preview, skill, tool } = useLocalSearchParams<{
    bot?: string | string[];
    preview?: string | string[];
    skill?: string | string[];
    tool?: string | string[];
  }>();
  const skillId = param(skill);
  const toolId = param(tool);
  const botTemplateId = param(bot);
  const initialCapability: CapabilitySelection | undefined = skillId
    ? { kind: 'skill', id: skillId }
    : toolId
      ? { kind: 'tool', id: toolId }
      : undefined;
  return (
    <AppEntry
      initialBotTemplateId={botTemplateId}
      initialCapability={initialCapability}
      preview={__DEV__ && param(preview) === '1'}
    />
  );
}
