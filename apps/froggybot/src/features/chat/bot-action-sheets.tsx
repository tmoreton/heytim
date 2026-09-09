import { ActionSheet } from '@/components/action-sheet';
import type { Bot, Group } from '@/lib/types';

export type BotAction = 'clear' | 'clearAndForget' | 'delete';

type Props = {
  bot?: Bot;
  group?: Group;
  menuOpen: boolean;
  pendingAction?: BotAction;
  onCloseMenu: () => void;
  onEditBot: () => void;
  onEditGroup: () => void;
  onDocuments: () => void;
  onBrowser: () => void;
  onSchedule: () => void;
  onShareSetup: () => void;
  onRequestAction: (action: BotAction) => void;
  onConfirmAction: (action: BotAction) => void;
  onCloseConfirmation: () => void;
};

export function ConversationActionSheets({
  bot,
  group,
  menuOpen,
  pendingAction,
  onCloseMenu,
  onEditBot,
  onEditGroup,
  onDocuments,
  onBrowser,
  onSchedule,
  onShareSetup,
  onRequestAction,
  onConfirmAction,
  onCloseConfirmation,
}: Props) {
  const menuTitle = group?.name ?? bot?.name ?? 'Conversation';
  const menuMessage = group
    ? group.isOwner
      ? 'Manage this room’s context, decisions, members, and recurring work.'
      : 'View this room’s shared context, decisions, members, and specialists.'
    : 'Manage this bot’s settings, files, recurring work, sharing, and conversation.';
  const menuOptions = group
    ? [
        {
          label: group.isOwner ? 'Room settings' : 'Room context',
          onPress: onEditGroup,
        },
        ...(group.isOwner ? [{ label: 'Tasks & runs', onPress: onSchedule }] : []),
      ]
    : [
        { label: 'Bot settings', onPress: onEditBot },
        { label: 'Files', onPress: onDocuments },
        { label: 'Browser connection', onPress: onBrowser },
        { label: 'Tasks & runs', onPress: onSchedule },
        { label: 'Share bot setup', onPress: onShareSetup },
        { label: 'Clear conversation', destructive: true, onPress: () => onRequestAction('clear' as const) },
        ...(bot?.systemRole === 'chief'
          ? []
          : [{ label: 'Delete bot', destructive: true, onPress: () => onRequestAction('delete' as const) }]),
      ];

  return (
    <>
      <ActionSheet
        visible={menuOpen}
        title={menuTitle}
        message={menuMessage}
        options={menuOptions}
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
