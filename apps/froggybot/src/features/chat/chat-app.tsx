import { useCallback, useMemo, useState } from 'react';
import {
  Alert,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  Share,
  useWindowDimensions,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ActionSheet } from '@/components/action-sheet';
import { endSession } from '@/lib/auth';
import { createApi } from '@/lib/api';
import type { Bot, BotDraft, CapabilitySelection, ConversationSelection, Group, GroupDraft, GroupMember, Invitation, Message } from '@/lib/types';

import { ConversationActionSheets, type BotAction } from './bot-action-sheets';
import { styles } from './chat-app.styles';
import type { ChatOverlay } from './chat-overlay';
import { ChatOverlays } from './chat-overlays';
import { ConversationPanel } from './conversation-panel';
import { ConversationDrawer } from './conversation-drawer';
import { ALL_BOTS_REPLY_TARGET } from './message-composer';
import { useAttachments } from './use-attachments';
import { useChatData } from './use-chat-data';
import { useConversationLinks } from './use-conversation-links';
import { useFilePreview } from './use-file-preview';
import { isActiveResponse } from './chat-state';

type Props = {
  demo: boolean;
  invitation?: Invitation;
  initialCapability?: CapabilitySelection;
  initialBotTemplateId?: string;
  onSignedOut: () => void;
};

const directTurnId = (message: Message) => message.id.replace(/-assistant$/, '');

export function ChatApp({ demo, invitation, initialCapability, initialBotTemplateId, onSignedOut }: Props) {
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const wide = width >= 760;
  const api = useMemo(() => createApi(demo), [demo]);
  const chat = useChatData(api);
  const {
    data,
    selection,
    messages,
    loadingMessages,
    loadingEarlierMessages,
    hasEarlierMessages,
    error,
    setError,
    pending,
    loadBootstrap,
    loadMessages,
    loadEarlierMessages,
    openConversation: setActiveConversation,
    upsertBot,
    upsertGroup,
    replaceBootstrap,
    refreshAfterMutation,
    clearMessages,
    markConversationProcessing,
  } = chat;
  const [drawerOpen, setDrawerOpen] = useState(wide);
  const [search, setSearch] = useState('');
  const [sending, setSending] = useState(false);
  const [overlay, setOverlay] = useState<ChatOverlay>(() => {
    if (initialBotTemplateId) return { kind: 'botLibrary' };
    if (initialCapability) return { kind: 'botEditor', mode: 'edit', capability: initialCapability };
    return { kind: 'none' };
  });
  const [botOnboardingDismissed, setBotOnboardingDismissed] = useState(false);
  const [replyBotId, setReplyBotId] = useState<string | null>();

  const selectedBot = selection?.kind === 'bot' ? data?.bots.find((bot) => bot.id === selection.id) : undefined;
  const suggestedCapability = overlay.kind === 'botEditor' ? overlay.capability : undefined;
  const editingBot = selectedBot ?? (suggestedCapability ? data?.bots[0] : undefined);
  const selectedGroup = selection?.kind === 'group' ? data?.groups.find((group) => group.id === selection.id) : undefined;
  const selected = selectedBot ?? selectedGroup;
  const filePreview = useFilePreview(api, selectedGroup?.id, setError);
  const activeBotName = messages.find(
    (message) => isActiveResponse(message) && message.authorType === 'bot',
  )?.authorName;
  const waitingBotCount = messages.filter(
    (message) => message.status === 'waiting' && message.authorType === 'bot',
  ).length;
  const activeDirectTurn = selectedBot
    ? [...messages]
        .reverse()
        .find(
          (message) =>
            message.role === 'assistant' && isActiveResponse(message),
        )
    : undefined;
  const activeReplyBotId = replyBotId === null
    ? undefined
    : replyBotId === ALL_BOTS_REPLY_TARGET && selectedGroup?.bots.length
      ? ALL_BOTS_REPLY_TARGET
    : selectedGroup?.bots.some((bot) => bot.id === replyBotId)
      ? replyBotId
      : selectedGroup && selectedGroup.bots.length > 1
        ? ALL_BOTS_REPLY_TARGET
        : selectedGroup?.bots[0]?.id;
  const selectedReplyBotName = activeReplyBotId === ALL_BOTS_REPLY_TARGET
    ? selectedGroup?.bots.find((bot) => bot.systemRole === 'chief')?.name ?? selectedGroup?.bots[0]?.name
    : selectedGroup?.bots.find((bot) => bot.id === activeReplyBotId)?.name;
  const attachmentDraft = useAttachments({
    api,
    disabled: !selected || (pending && !selectedBot) || sending,
    setError,
  });
  const { attachments, uploading: uploadingAttachment } = attachmentDraft;
  const clearAttachmentDraft = attachmentDraft.clear;
  const botLibraryOnboarding = Boolean(
    data?.needsBotOnboarding && !botOnboardingDismissed && overlay.kind === 'none',
  );
  const botLibraryOpen = overlay.kind === 'botLibrary' || botLibraryOnboarding;

  const openConversation = useCallback((next: ConversationSelection, closeDrawer = true) => {
    clearAttachmentDraft();
    setActiveConversation(next);
    if (closeDrawer) setDrawerOpen(false);
  }, [clearAttachmentDraft, setActiveConversation]);

  const links = useConversationLinks({
    api,
    demo,
    invitation,
    loadBootstrap,
    openConversation,
  });
  const baseContentHidden =
    (!wide && drawerOpen) || overlay.kind !== 'none' || botLibraryOnboarding || Boolean(links.pendingSkill) || Boolean(filePreview.previewFile);

  const selectBot = (bot: Bot) => {
    openConversation({ kind: 'bot', id: bot.id }, !wide);
  };

  const selectGroup = (group: Group) => {
    openConversation({ kind: 'group', id: group.id }, !wide);
  };

  const saveBot = async (value: BotDraft) => {
    const editing = overlay.kind === 'botEditor' && overlay.mode === 'edit';
    const saved = await api.saveBot(value, editing ? editingBot?.id : undefined);
    clearAttachmentDraft();
    upsertBot(saved);
  };

  const installBotTemplate = async (templateId: string) => {
    const saved = await api.installBotTemplate(templateId);
    setOverlay({ kind: 'botLibrary' });
    clearAttachmentDraft();
    upsertBot(saved, true);
    return saved;
  };

  const saveGroup = async (value: GroupDraft) => {
    const editing = overlay.kind === 'groupEditor' && overlay.mode === 'edit';
    const saved = await api.saveGroup(value, editing ? selectedGroup?.id : undefined);
    clearAttachmentDraft();
    upsertGroup(saved);
  };

  const send = async (text: string) => {
    if ((!text && attachments.length === 0) || !selected || sending || (pending && !selectedBot) || uploadingAttachment) return false;
    setSending(true);
    try {
      if (selectedGroup) {
        await api.sendGroupMessage(
          selectedGroup.id,
          text,
          activeReplyBotId,
          attachments.map((item) => item.id),
        );
      }
      else if (selectedBot) await api.sendMessage(selectedBot, text, attachments.map((item) => item.id));
      if (selection && (selectedBot || activeReplyBotId)) {
        markConversationProcessing(selection, selectedBot?.name ?? selectedReplyBotName);
      }
      attachmentDraft.clear();
      await loadMessages();
      return true;
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not send that message.');
      return false;
    } finally {
      setSending(false);
    }
  };

  const stopResponse = async () => {
    if (!selectedBot || !activeDirectTurn) return;
    try {
      await api.cancelMessage(selectedBot.id, directTurnId(activeDirectTurn));
      await loadMessages();
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not stop that response.');
    }
  };

  const respondToApproval = async (
    message: Message,
    always?: boolean,
  ) => {
    if (!selectedBot || message.status !== 'awaiting_approval') return;
    try {
      if (always === undefined) {
        await api.cancelMessage(selectedBot.id, directTurnId(message));
      } else {
        await api.approveMessage(selectedBot.id, directTurnId(message), always);
      }
      await loadMessages();
      if (always) await loadBootstrap();
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not update that approval request.');
    }
  };

  const shareBot = () => {
    if (!selectedBot) return;
    api
      .share(selectedBot.id, 'bot')
      .then((url) =>
        Share.share({
          title: `Share ${selectedBot.name}`,
          message: `Add ${selectedBot.name} to FroggyBot: ${url}`,
          url,
        }),
      )
      .catch((value) => Alert.alert('Could not share', value instanceof Error ? value.message : 'Please try again.'));
  };

  const openCapabilityEditor = (capability: CapabilitySelection) => {
    const bot = selectedBot ?? data?.bots[0];
    if (bot) setActiveConversation({ kind: 'bot', id: bot.id });
    setOverlay({ kind: 'botEditor', mode: bot ? 'edit' : 'new', capability });
  };

  const runBotDeletion = async (requestedAction?: BotAction) => {
    if (!selectedBot || overlay.kind !== 'botConfirmation') return;
    const action = requestedAction ?? overlay.action;
    try {
      if (action === 'clear' || action === 'clearAndForget') {
        await api.clearBotChat(selectedBot.id, action === 'clearAndForget');
        const next = await api.bootstrap();
        replaceBootstrap(next);
        clearMessages();
        setOverlay({ kind: 'none' });
        return;
      }
      await api.deleteBot(selectedBot.id);
      clearAttachmentDraft();
      await refreshAfterMutation();
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not delete that conversation.');
    }
  };

  const shareGroup = async () => {
    if (!selectedGroup) throw new Error('Choose a group first.');
    return api.shareGroup(selectedGroup.id);
  };

  const removeGroupMember = async (member: GroupMember) => {
    if (!selectedGroup) return;
    await api.removeGroupMember(selectedGroup.id, member.id);
    clearAttachmentDraft();
    await loadBootstrap();
  };

  const deleteGroup = async () => {
    if (!selectedGroup) return;
    await api.deleteGroup(selectedGroup.id);
    clearAttachmentDraft();
    await refreshAfterMutation();
  };

  const deleteGroupDecision = async (decisionId: string) => {
    if (!selectedGroup) return;
    await api.deleteGroupDecision(selectedGroup.id, decisionId);
    upsertGroup({
      ...selectedGroup,
      decisions: selectedGroup.decisions.filter((item) => item.id !== decisionId),
    });
  };

  const refreshAfterSchedule = async () => {
    clearMessages(true);
    await Promise.all([loadMessages(), loadBootstrap()]);
  };

  const signOut = async () => {
    if (!demo) {
      try {
        await links.unregisterPushToken();
      } catch (value) {
        console.warn('Could not unregister the push token.', value);
      }
      await endSession();
    }
    onSignedOut();
  };

  const deleteAccount = async () => {
    if (demo) return;
    await api.deleteAccount();
    try {
      await endSession();
    } catch (value) {
      console.warn('Account deletion started, but local sign-out reported an error.', value);
    }
    setOverlay({ kind: 'none' });
    onSignedOut();
  };

  const drawer = (
    <ConversationDrawer
      bots={data?.bots ?? []}
      groups={data?.groups ?? []}
      selection={selection}
      search={search}
      demo={demo}
      topInset={insets.top}
      bottomInset={insets.bottom}
      onSearchChange={setSearch}
      onSelectBot={selectBot}
      onSelectGroup={selectGroup}
      onOpenBotLibrary={() => {
        setDrawerOpen(false);
        setBotOnboardingDismissed(true);
        setOverlay({ kind: 'botLibrary' });
      }}
      onCreateBot={() => {
        setDrawerOpen(false);
        setOverlay({ kind: 'botEditor', mode: 'new' });
      }}
      onCreateGroup={() => {
        setDrawerOpen(false);
        setOverlay({ kind: 'groupEditor', mode: 'new' });
      }}
      onOpenAccount={() => {
        setDrawerOpen(false);
        setOverlay({ kind: 'account' });
      }}
      onClose={!wide ? () => setDrawerOpen(false) : undefined}
    />
  );

  return (
    <View style={styles.safeArea}>
      <KeyboardAvoidingView
        accessibilityElementsHidden={baseContentHidden}
        aria-hidden={baseContentHidden}
        importantForAccessibility={baseContentHidden ? 'no-hide-descendants' : 'auto'}
        style={styles.safeArea}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.shell}>
          {wide && drawerOpen ? <View style={styles.wideDrawer}>{drawer}</View> : null}
          <ConversationPanel
            browserApi={api}
            browserVisible={overlay.kind === 'browser'} browserUrl={overlay.kind === 'browser' ? overlay.url : undefined}
            onOpenBrowser={(url) => setOverlay({ kind: 'browser', url })}
            onCloseBrowser={() => setOverlay({ kind: 'none' })}
            onBrowserResumed={async () => { await Promise.all([loadMessages(), loadBootstrap()]); }}
            key={selectedGroup ? `group:${selectedGroup.id}` : `bot:${selectedBot?.id ?? 'none'}`}
            fullWidth={Platform.OS !== 'web' || !wide}
            bot={selectedBot}
            group={selectedGroup}
            messages={messages}
            loading={loadingMessages}
            loadingEarlier={loadingEarlierMessages}
            hasEarlier={hasEarlierMessages}
            error={error}
            attachments={attachments}
            pending={pending}
            sending={sending}
            uploading={uploadingAttachment}
            canStop={Boolean(activeDirectTurn)}
            activeBotName={activeBotName}
            waitingBotCount={waitingBotCount}
            activeReplyBotId={activeReplyBotId}
            topInset={insets.top}
            bottomInset={insets.bottom}
            onError={setError}
            onDismissError={() => setError('')}
            onToggleDrawer={() => setDrawerOpen((value) => !value)}
            onEditGroup={() => setOverlay({ kind: 'groupEditor', mode: 'edit' })}
            onOpenMenu={() => setOverlay({ kind: selectedGroup ? 'groupMenu' : 'botMenu' })}
            onAddAttachment={() => void attachmentDraft.pick()}
            onRemoveAttachment={attachmentDraft.remove}
            onReplyTargetChange={setReplyBotId}
            onSend={send}
            onStop={() => void stopResponse()}
            onApprove={respondToApproval}
            onReject={(message) => respondToApproval(message)}
            onOpenFile={filePreview.openFile}
            onResolveFile={filePreview.resolveFile}
            onSaveDecision={async (message) => {
              if (!selectedGroup) return;
              const decision = await api.saveGroupDecision(selectedGroup.id, message.id);
              upsertGroup({ ...selectedGroup, decisions: [decision, ...selectedGroup.decisions.filter((item) => item.id !== decision.id)] });
            }}
            onLoadEarlier={loadEarlierMessages}
          />

        </View>
      </KeyboardAvoidingView>

      <Modal
        animationType="fade"
        transparent
        visible={!wide && drawerOpen}
        onRequestClose={() => setDrawerOpen(false)}>
        <View
          accessibilityLabel="Chats and groups"
          accessibilityViewIsModal
          aria-modal
          role="dialog"
          style={styles.mobileDrawerLayer}>
          <Pressable
            accessibilityLabel="Dismiss chats and groups"
            accessibilityRole="button"
            style={styles.backdrop}
            onPress={() => setDrawerOpen(false)}
          />
          <View style={[styles.mobileDrawer, { width: Math.min(width * 0.86, 340) }]}>{drawer}</View>
        </View>
      </Modal>

      <ChatOverlays
        api={api}
        overlay={overlay}
        data={data}
        demo={demo}
        editingBot={editingBot}
        selectedGroup={selectedGroup}
        suggestedCapability={suggestedCapability}
        botLibraryOpen={botLibraryOpen}
        botLibraryOnboarding={botLibraryOnboarding}
        initialBotTemplateId={initialBotTemplateId}
        previewFile={filePreview.previewFile}
        onOverlayChange={setOverlay}
        onDismissBotLibrary={() => {
          setBotOnboardingDismissed(true);
          setOverlay({ kind: 'none' });
        }}
        onSaveBot={saveBot}
        onInstallBotTemplate={installBotTemplate}
        onSaveGroup={saveGroup}
        onShareGroup={shareGroup}
        onRemoveGroupMember={removeGroupMember}
        onDeleteGroup={deleteGroup}
        onDeleteGroupDecision={deleteGroupDecision}
        onBootstrapChanged={loadBootstrap}
        onOpenCapabilityEditor={openCapabilityEditor}
        onDeleteAccount={deleteAccount}
        onSignOut={signOut}
        onScheduleTriggered={refreshAfterSchedule}
        onOpenFile={filePreview.openFile}
        onClosePreview={filePreview.closePreview}
        onResolveFile={filePreview.resolveFile}
      />
      <ConversationActionSheets
        bot={selectedBot}
        group={selectedGroup}
        menuOpen={overlay.kind === 'botMenu' || overlay.kind === 'groupMenu'}
        pendingAction={overlay.kind === 'botConfirmation' ? overlay.action : undefined}
        onCloseMenu={() => setOverlay({ kind: 'none' })}
        onEditBot={() => setOverlay({ kind: 'botEditor', mode: 'edit' })}
        onBrowser={() => setOverlay({ kind: 'browser' })}
        onEditGroup={() => setOverlay({ kind: 'groupEditor', mode: 'edit' })}
        onDocuments={() => {
          if (selectedBot) setOverlay({ kind: 'documents', bot: selectedBot });
        }}
        onSchedule={() => {
          if (selectedGroup?.isOwner) setOverlay({ kind: 'groupSchedule', group: selectedGroup });
          else if (selectedBot) setOverlay({ kind: 'schedule', bot: selectedBot });
        }}
        onShareSetup={shareBot}
        onRequestAction={(action) => setOverlay({ kind: 'botConfirmation', action })}
        onConfirmAction={(action) => void runBotDeletion(action)}
        onCloseConfirmation={() => setOverlay({ kind: 'none' })}
      />
      <ActionSheet
        visible={Boolean(links.pendingSkill)}
        title="Install shared skill?"
        message="Skills change how your bots work. Only install skills from people you trust."
        options={[{ label: 'Install skill', onPress: links.installSkill }]}
        onClose={links.dismissSkill}
      />
    </View>
  );
}
