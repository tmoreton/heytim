import { ActionSheet } from '@/components/action-sheet';
import type { Bot } from '@/lib/types';

export type BotAction = 'clear' | 'clearAndForget' | 'delete';

type Props = {
  bot?: Bot;
  menuOpen: boolean;
  pendingAction?: BotAction;
  onCloseMenu: () => void;
  onEditBot: () => void;
  onDocuments: () => void;
  onSchedule: () => void;
  onShareSetup: () => void;
  onRequestAction: (action: BotAction) => void;
  onConfirmAction: (action: BotAction) => void;
  onCloseConfirmation: () => void;
};

export function BotActionSheets({
  bot,
  menuOpen,
  pendingAction,
  onCloseMenu,
  onEditBot,
  onDocuments,
  onSchedule,
  onShareSetup,
  onRequestAction,
  onConfirmAction,
  onCloseConfirmation,
}: Props) {
  return (
    <>
      <ActionSheet
        visible={menuOpen}
        title={bot?.name ?? 'FroggyBot'}
        message="Open its documents, schedule its work, or manage this conversation."
        options={[
          { label: 'Edit bot', onPress: onEditBot },
          { label: 'Documents', onPress: onDocuments },
          { label: 'Scheduled tasks', onPress: onSchedule },
          { label: 'Share bot setup', onPress: onShareSetup },
          { label: 'Clear conversation', destructive: true, onPress: () => onRequestAction('clear') },
          ...(bot?.systemRole === 'chief'
            ? []
            : [{ label: 'Delete bot', destructive: true, onPress: () => onRequestAction('delete') }]),
        ]}
        onClose={onCloseMenu}
      />
      <ActionSheet
        visible={Boolean(pendingAction)}
        title={pendingAction === 'delete' ? `Delete ${bot?.name ?? 'this bot'}?` : 'Clear this conversation?'}
        message={
          pendingAction === 'delete'
            ? 'This permanently deletes the FroggyBot, its direct chat, conversation memory, generated documents, and removes it from your groups.'
            : 'Choose whether to delete only the visible messages or also forget this bot’s conversation summary and raw memory events. Your personal facts and preferences stay in Memory settings.'
        }
        options={pendingAction === 'delete'
          ? [{ label: 'Delete bot', destructive: true, onPress: () => onConfirmAction('delete') }]
          : [
              { label: 'Clear messages only', destructive: true, onPress: () => onConfirmAction('clear') },
              { label: 'Clear messages and conversation memory', destructive: true, onPress: () => onConfirmAction('clearAndForget') },
            ]}
        onClose={onCloseConfirmation}
      />
    </>
  );
}
