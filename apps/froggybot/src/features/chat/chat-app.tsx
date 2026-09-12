import { useCallback, useMemo, useState } from 'react';
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  useWindowDimensions,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ActionSheet } from '@/components/action-sheet';
import { createApi } from '@/lib/api';
import {
  endSession,
  useAttachments,
  useChatActions,
  useChatData,
  useConversationLinks,
  useFilePreview,
  type ChatOverlay,
} from '@froggybot/expo-client';
import type { Bot, CapabilitySelection, ConversationSelection, Group, Invitation } from '@froggybot/contracts';
import { isActiveResponse } from '@froggybot/client';

import { ConversationActionSheets } from './bot-action-sheets';
import { styles } from './chat-app.styles';
import { ChatOverlays } from './chat-overlays';
import { ConversationPanel } from './conversation-panel';
import { ConversationDrawer } from './conversation-drawer';
import { ALL_BOTS_REPLY_TARGET } from './message-composer';

type Props = {
  demo: boolean;
  invitation?: Invitation;
  initialCapability?: CapabilitySelection;
  initialBotTemplateId?: string;
  onSignedOut: () => void;
};

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
    constraints: data?.constraints,
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
  const actions = useChatActions({
    api,
    demo,
    overlay,
    setOverlay,
    selectedBot,
    editingBot,
    selectedGroup,
    selection,
    activeReplyBotId,
    selectedReplyBotName,
    sending,
    setSending,
    chat,
    attachments: attachmentDraft,
    unregisterPushToken: links.unregisterPushToken,
    endSession,
    onSignedOut,
  });
  const baseContentHidden =
    (!wide && drawerOpen)
    || overlay.kind !== 'none'
    || botLibraryOnboarding
    || attachmentDraft.pickerOpen
    || Boolean(links.pendingSkill)
    || Boolean(filePreview.previewFile);

  const selectBot = (bot: Bot) => {
    openConversation({ kind: 'bot', id: bot.id }, !wide);
  };

  const selectGroup = (group: Group) => {
    openConversation({ kind: 'group', id: group.id }, !wide);
  };

  const openCapabilityEditor = (capability: CapabilitySelection) => {
    const bot = selectedBot ?? data?.bots[0];
    if (bot) setActiveConversation({ kind: 'bot', id: bot.id });
    setOverlay({ kind: 'botEditor', mode: bot ? 'edit' : 'new', capability });
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
            canStop={Boolean(actions.activeDirectTurn)}
            activeBotName={activeBotName}
            waitingBotCount={waitingBotCount}
            activeReplyBotId={activeReplyBotId}
            topInset={insets.top}
            bottomInset={insets.bottom}
            maxMessageLength={data?.constraints?.messageMaxLength ?? 0}
            onError={setError}
            onDismissError={() => setError('')}
            onToggleDrawer={() => setDrawerOpen((value) => !value)}
            onEditGroup={() => setOverlay({ kind: 'groupEditor', mode: 'edit' })}
            onOpenMenu={() => setOverlay({ kind: selectedGroup ? 'groupMenu' : 'botMenu' })}
            onAddAttachment={attachmentDraft.openPicker}
            onRemoveAttachment={attachmentDraft.remove}
            onReplyTargetChange={setReplyBotId}
            onSend={actions.send}
            onStop={() => void actions.stopResponse()}
            onApprove={actions.respondToApproval}
            onReject={(message) => actions.respondToApproval(message)}
            onOpenFile={filePreview.openFile}
            onResolveFile={filePreview.resolveFile}
            onSaveDecision={actions.saveGroupDecision}
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
        onSaveBot={actions.saveBot}
        onInstallBotTemplate={actions.installBotTemplate}
        onSaveGroup={actions.saveGroup}
        onShareGroup={actions.shareGroup}
        onRemoveGroupMember={actions.removeGroupMember}
        onDeleteGroup={actions.deleteGroup}
        onDeleteGroupDecision={actions.deleteGroupDecision}
        onBootstrapChanged={loadBootstrap}
        onOpenCapabilityEditor={openCapabilityEditor}
        onDeleteAccount={actions.deleteAccount}
        onSignOut={actions.signOut}
        onScheduleTriggered={actions.refreshAfterSchedule}
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
          if (selectedGroup?.allowedActions?.includes('schedule')) setOverlay({ kind: 'groupSchedule', group: selectedGroup });
          else if (selectedBot) setOverlay({ kind: 'schedule', bot: selectedBot });
        }}
        onShareSetup={actions.shareBot}
        onRequestAction={(action) => setOverlay({ kind: 'botConfirmation', action })}
        onConfirmAction={(action) => void actions.runBotDeletion(action)}
        onCloseConfirmation={() => setOverlay({ kind: 'none' })}
      />
      <ActionSheet
        visible={attachmentDraft.pickerOpen}
        title="Add attachment"
        message="Choose photos from your library or attach a document from Files."
        options={[
          { label: 'Photo library', onPress: () => void attachmentDraft.pickPhotos() },
          { label: 'Files', onPress: () => void attachmentDraft.pickFiles() },
        ]}
        onClose={attachmentDraft.closePicker}
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
