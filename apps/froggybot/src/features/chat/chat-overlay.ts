import type { Bot, CapabilitySelection, Group } from '@/lib/types';

import type { BotAction } from './bot-action-sheets';

export type ChatOverlay =
  | { kind: 'none' }
  | { kind: 'botEditor'; mode: 'new' | 'edit'; capability?: CapabilitySelection }
  | { kind: 'botLibrary' }
  | { kind: 'groupEditor'; mode: 'new' | 'edit' }
  | { kind: 'skillLibrary' }
  | { kind: 'account' }
  | { kind: 'memory' }
  | { kind: 'browser' }
  | { kind: 'documents'; bot: Bot }
  | { kind: 'schedule'; bot: Bot }
  | { kind: 'groupSchedule'; group: Group }
  | { kind: 'botMenu' }
  | { kind: 'groupMenu' }
  | { kind: 'botConfirmation'; action: BotAction };
