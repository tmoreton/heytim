import { useLocalSearchParams } from 'expo-router';

import { AppEntry } from '@/features/app/app-entry';
import { firstRouteParam } from '@froggybot/client';
import type { CapabilitySelection } from '@froggybot/contracts';

export default function AppPage() {
  const { bot, preview, skill, tool } = useLocalSearchParams<{
    bot?: string | string[];
    preview?: string | string[];
    skill?: string | string[];
    tool?: string | string[];
  }>();
  const skillId = firstRouteParam(skill);
  const toolId = firstRouteParam(tool);
  const botTemplateId = firstRouteParam(bot);
  const initialCapability: CapabilitySelection | undefined = skillId
    ? { kind: 'skill', id: skillId }
    : toolId
      ? { kind: 'tool', id: toolId }
      : undefined;
  return (
    <AppEntry
      initialBotTemplateId={botTemplateId}
      initialCapability={initialCapability}
      preview={__DEV__ && firstRouteParam(preview) === '1'}
    />
  );
}
