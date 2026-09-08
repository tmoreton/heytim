import { ActionSheet } from '@/components/action-sheet';
import type { Bot } from '@/lib/types';

export type BotAction = 'clear' | 'delete';

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
  onConfirmAction: () => void;
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
            ? 'This permanently deletes the FroggyBot, its direct chat, generated documents, and removes it from your groups.'
            : 'This permanently deletes every message in this direct chat but keeps the FroggyBot.'
        }
        options={[
          {
            label: pendingAction === 'delete' ? 'Delete bot' : 'Clear conversation',
            destructive: true,
            onPress: onConfirmAction,
          },
        ]}
        onClose={onCloseConfirmation}
      />
    </>
  );
}
