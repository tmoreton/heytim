import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  KeyboardAvoidingView,
  Linking,
  Platform,
  Pressable,
  Share,
  StyleSheet,
  useWindowDimensions,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ActionSheet } from '@/components/action-sheet';
import { endSession } from '@/lib/auth';
import { createApi } from '@/lib/api';
import type { Attachment, Bootstrap, Bot, BotDraft, Group, GroupDraft, GroupMember, Invitation, Message } from '@/lib/types';

import { AccountSettings } from './account-settings';
import { BotEditor } from './bot-editor';
import { ConversationPanel } from './conversation-panel';
import { ConversationDrawer, type ConversationSelection as Selection } from './conversation-drawer';
import { GroupEditor } from './group-editor';
import { ALL_BOTS_REPLY_TARGET } from './message-composer';
import { ScheduledTasks } from './scheduled-tasks';
import { SkillLibrary } from './skill-library';
import { useAttachments } from './use-attachments';
import { useConversationLinks } from './use-conversation-links';
import { useMessageDictation } from './use-message-dictation';

type Props = {
  demo: boolean;
  invitation?: Invitation;
  onSignedOut: () => void;
};

const MESSAGE_REFRESH_MS = 900;

const directTurnId = (message: Message) =>
  message.id.endsWith('-assistant')
    ? message.id.slice(0, -'-assistant'.length)
    : message.id;

export function ChatApp({ demo, invitation, onSignedOut }: Props) {
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const wide = width >= 760;
  const api = useMemo(() => createApi(demo), [demo]);
  const messageRequest = useRef(0);
  const [data, setData] = useState<Bootstrap>();
  const [selection, setSelection] = useState<Selection>();
  const [messages, setMessages] = useState<Message[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(wide);
  const [search, setSearch] = useState('');
  const [draft, setDraft] = useState('');
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [editor, setEditor] = useState<'new' | 'edit' | undefined>();
  const [groupEditor, setGroupEditor] = useState<'new' | 'edit' | undefined>();
  const [skillLibraryOpen, setSkillLibraryOpen] = useState(false);
  const [botMenuOpen, setBotMenuOpen] = useState(false);
  const [accountSettingsOpen, setAccountSettingsOpen] = useState(false);
  const [scheduleBot, setScheduleBot] = useState<Bot>();
  const [pendingBotAction, setPendingBotAction] = useState<'clear' | 'delete'>();
  const [replyBotId, setReplyBotId] = useState<string | null>();

  const selectedBot = selection?.kind === 'bot' ? data?.bots.find((bot) => bot.id === selection.id) : undefined;
  const selectedGroup = selection?.kind === 'group' ? data?.groups.find((group) => group.id === selection.id) : undefined;
  const selected = selectedBot ?? selectedGroup;
  const pending = messages.some((message) =>
    ['pending', 'running', 'waiting', 'needs_input', 'awaiting_approval'].includes(message.status),
  );
  const refreshing = messages.some((message) =>
    ['pending', 'running', 'waiting'].includes(message.status),
  );
  const activeBotName = messages.find(
    (message) => ['pending', 'running'].includes(message.status) && message.authorType === 'bot',
  )?.authorName;
  const waitingBotCount = messages.filter(
    (message) => message.status === 'waiting' && message.authorType === 'bot',
  ).length;
  const activeDirectTurn = selectedBot
    ? [...messages]
        .reverse()
        .find(
          (message) =>
            message.role === 'assistant' && ['pending', 'running'].includes(message.status),
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
  const dictation = useMessageDictation(draft, setDraft, setError);
  const attachmentDraft = useAttachments({
    api,
    disabled: !selectedBot || pending || sending,
    setError,
  });
  const { attachments, uploading: uploadingAttachment } = attachmentDraft;
  const { listening } = dictation;
  const clearAttachmentDraft = attachmentDraft.clear;

  const chooseAvailableSelection = useCallback((next: Bootstrap, current?: Selection): Selection | undefined => {
    if (current?.kind === 'bot' && next.bots.some((bot) => bot.id === current.id)) return current;
    if (current?.kind === 'group' && next.groups.some((group) => group.id === current.id)) return current;
    if (next.groups[0]) return { kind: 'group', id: next.groups[0].id };
    if (next.bots[0]) return { kind: 'bot', id: next.bots[0].id };
    return undefined;
  }, []);


  const loadBootstrap = useCallback(async () => {
    try {
      const next = await api.bootstrap();
      setData(next);
      setSelection((current) => chooseAvailableSelection(next, current));
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not load your bots.');
    }
  }, [api, chooseAvailableSelection]);

  const openConversation = useCallback((next: Selection, closeDrawer = true) => {
    setMessages([]);
    setLoadingMessages(true);
    clearAttachmentDraft();
    setSelection(next);
    if (closeDrawer) setDrawerOpen(false);
  }, [clearAttachmentDraft]);

  const links = useConversationLinks({
    api,
    demo,
    invitation,
    loadBootstrap,
    openConversation,
  });

  const loadMessages = useCallback(async () => {
    if (!selection) return;
    const requestId = ++messageRequest.current;
    try {
      const next = selection.kind === 'group'
        ? await api.groupMessages(selection.id)
        : await api.messages(selection.id);
      if (requestId === messageRequest.current) {
        setMessages(next);
        setError('');
      }
    } catch (value) {
      if (requestId === messageRequest.current) {
        setError(value instanceof Error ? value.message : 'Could not load this conversation.');
      }
    } finally {
      if (requestId === messageRequest.current) setLoadingMessages(false);
    }
  }, [api, selection]);

  useEffect(() => {
    let active = true;
    api
      .bootstrap()
      .then((next) => {
        if (!active) return;
        setData(next);
        setLoadingMessages(Boolean(next.groups[0] ?? next.bots[0]));
        setSelection((current) => chooseAvailableSelection(next, current));
      })
      .catch((value) => {
        if (active) setError(value instanceof Error ? value.message : 'Could not load your bots.');
      });
    return () => {
      active = false;
    };
  }, [api, chooseAvailableSelection]);

  useEffect(() => {
    if (!selection) return;
    let active = true;
    const requestId = ++messageRequest.current;
    const request = selection.kind === 'group' ? api.groupMessages(selection.id) : api.messages(selection.id);
    request
      .then((next) => {
        if (!active || requestId !== messageRequest.current) return;
        setMessages(next);
        setError('');
      })
      .catch((value) => {
        if (active && requestId === messageRequest.current) {
          setError(value instanceof Error ? value.message : 'Could not load this conversation.');
        }
      })
      .finally(() => {
        if (active && requestId === messageRequest.current) setLoadingMessages(false);
      });
    return () => {
      active = false;
    };
  }, [api, selection]);

  useEffect(() => {
    if (!refreshing) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      await loadMessages();
      if (active) timer = setTimeout(poll, MESSAGE_REFRESH_MS);
    };
    timer = setTimeout(poll, MESSAGE_REFRESH_MS);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [loadMessages, refreshing]);

  const selectBot = (bot: Bot) => {
    dictation.abort();
    openConversation({ kind: 'bot', id: bot.id }, !wide);
  };

  const selectGroup = (group: Group) => {
    dictation.abort();
    openConversation({ kind: 'group', id: group.id }, !wide);
  };

  const saveBot = async (value: BotDraft) => {
    const saved = await api.saveBot(value, editor === 'edit' ? selectedBot?.id : undefined);
    setData((current) => {
      if (!current) return current;
      const exists = current.bots.some((bot) => bot.id === saved.id);
      return { ...current, bots: exists ? current.bots.map((bot) => (bot.id === saved.id ? saved : bot)) : [saved, ...current.bots] };
    });
    setMessages([]);
    setLoadingMessages(true);
    clearAttachmentDraft();
    setSelection({ kind: 'bot', id: saved.id });
  };

  const saveGroup = async (value: GroupDraft) => {
    const saved = await api.saveGroup(value, groupEditor === 'edit' ? selectedGroup?.id : undefined);
    setData((current) => {
      if (!current) return current;
      const exists = current.groups.some((group) => group.id === saved.id);
      return {
        ...current,
        groups: exists ? current.groups.map((group) => (group.id === saved.id ? saved : group)) : [saved, ...current.groups],
      };
    });
    setMessages([]);
    setLoadingMessages(true);
    clearAttachmentDraft();
    setSelection({ kind: 'group', id: saved.id });
  };

  const send = async () => {
    const text = draft.trim();
    if ((!text && attachments.length === 0) || !selected || sending || pending || uploadingAttachment) return;
    setSending(true);
    dictation.stop();
    setDraft('');
    try {
      if (selectedGroup) await api.sendGroupMessage(selectedGroup.id, text, activeReplyBotId);
      else if (selectedBot) await api.sendMessage(selectedBot, text, attachments.map((item) => item.id));
      attachmentDraft.clear();
      await loadMessages();
    } catch (value) {
      setDraft(text);
      setError(value instanceof Error ? value.message : 'Could not send that message.');
    } finally {
      setSending(false);
    }
  };

  const openFile = async (file: Attachment) => {
    try {
      const url = await api.downloadFile(file.id);
      await Linking.openURL(url);
      setError('');
    } catch (value) {
      const error = value instanceof Error ? value : new Error('Could not download that file.');
      setError(error.message);
      throw error;
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

  const respondToApproval = async (message: Message, approved: boolean) => {
    if (!selectedBot || message.status !== 'awaiting_approval') return;
    try {
      if (approved) await api.approveMessage(selectedBot.id, directTurnId(message));
      else await api.cancelMessage(selectedBot.id, directTurnId(message));
      await loadMessages();
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not update that approval request.');
    }
  };

  const share = (scope: 'bot' | 'chat') => {
    if (!selectedBot) return;
    api
      .share(selectedBot.id, scope)
      .then((url) =>
        Share.share({
          title: `Share ${selectedBot.name}`,
          message: scope === 'chat' ? `Open my conversation with ${selectedBot.name}: ${url}` : `Add ${selectedBot.name} to FroggyBot: ${url}`,
          url,
        }),
      )
      .catch((value) => Alert.alert('Could not share', value instanceof Error ? value.message : 'Please try again.'));
  };

  const showBotOptions = () => {
    setBotMenuOpen(true);
  };

  const refreshAfterDeletion = async () => {
    const next = await api.bootstrap();
    const nextSelection = chooseAvailableSelection(next, selection);
    messageRequest.current += 1;
    setData(next);
    setMessages([]);
    setError('');
    clearAttachmentDraft();
    setSelection(nextSelection);
    setLoadingMessages(Boolean(nextSelection));
  };

  const runBotDeletion = async () => {
    if (!selectedBot || !pendingBotAction) return;
    dictation.abort();
    try {
      if (pendingBotAction === 'clear') {
        await api.clearBotChat(selectedBot.id);
        const next = await api.bootstrap();
        messageRequest.current += 1;
        setData(next);
        setMessages([]);
        setError('');
        setLoadingMessages(false);
        return;
      }
      await api.deleteBot(selectedBot.id);
      await refreshAfterDeletion();
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
    const next = await api.bootstrap();
    setData(next);
    clearAttachmentDraft();
    setSelection((current) => chooseAvailableSelection(next, current));
  };

  const deleteGroup = async () => {
    if (!selectedGroup) return;
    dictation.abort();
    await api.deleteGroup(selectedGroup.id);
    await refreshAfterDeletion();
  };

  const signOut = async () => {
    dictation.abort();
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
    dictation.abort();
    await api.deleteAccount();
    try {
      await endSession();
    } catch (value) {
      console.warn('Account deletion started, but local sign-out reported an error.', value);
    }
    setAccountSettingsOpen(false);
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
      onCreateBot={() => setEditor('new')}
      onCreateGroup={() => setGroupEditor('new')}
      onOpenAccount={() => setAccountSettingsOpen(true)}
    />
  );

  return (
    <View style={styles.safeArea}>
      <KeyboardAvoidingView style={styles.safeArea} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.shell}>
          {wide && drawerOpen ? <View style={styles.wideDrawer}>{drawer}</View> : null}
          <ConversationPanel
            bot={selectedBot}
            group={selectedGroup}
            messages={messages}
            loading={loadingMessages}
            error={error}
            draft={draft}
            attachments={attachments}
            listening={listening}
            pending={pending}
            sending={sending}
            uploading={uploadingAttachment}
            canStop={Boolean(activeDirectTurn)}
            activeBotName={activeBotName}
            waitingBotCount={waitingBotCount}
            activeReplyBotId={activeReplyBotId}
            topInset={insets.top}
            bottomInset={insets.bottom}
            onDismissError={() => setError('')}
            onToggleDrawer={() => setDrawerOpen((value) => !value)}
            onEditBot={() => setEditor('edit')}
            onEditGroup={() => setGroupEditor('edit')}
            onOpenBotMenu={showBotOptions}
            onDraftChange={setDraft}
            onAddAttachment={() => void attachmentDraft.pick()}
            onRemoveAttachment={attachmentDraft.remove}
            onReplyTargetChange={setReplyBotId}
            onToggleDictation={() => void dictation.toggle()}
            onSend={() => void send()}
            onStop={() => void stopResponse()}
            onApprove={(message) => respondToApproval(message, true)}
            onReject={(message) => respondToApproval(message, false)}
            onOpenFile={openFile}
          />

          {!wide && drawerOpen ? (
            <View style={styles.mobileDrawerLayer}>
              <Pressable style={styles.backdrop} onPress={() => setDrawerOpen(false)} />
              <View style={[styles.mobileDrawer, { width: Math.min(width * 0.86, 340) }]}>{drawer}</View>
            </View>
          ) : null}
        </View>
      </KeyboardAvoidingView>

      {editor ? (
        <BotEditor
          key={`${editor}-${selectedBot?.id ?? 'new'}`}
          bot={editor === 'edit' ? selectedBot : undefined}
          tools={data?.tools ?? []}
          skills={data?.skills ?? []}
          onClose={() => setEditor(undefined)}
          onSave={saveBot}
          onLoadSkill={api.skill}
        />
      ) : null}
      {groupEditor ? (
        <GroupEditor
          key={`${groupEditor}-${selectedGroup?.id ?? 'new'}`}
          group={groupEditor === 'edit' ? selectedGroup : undefined}
          bots={data?.bots ?? []}
          onClose={() => setGroupEditor(undefined)}
          onSave={saveGroup}
          onShare={shareGroup}
          onRemoveMember={removeGroupMember}
          onDelete={deleteGroup}
        />
      ) : null}
      {skillLibraryOpen ? (
        <SkillLibrary
          skills={data?.skills ?? []}
          tools={data?.tools ?? []}
          onClose={() => setSkillLibraryOpen(false)}
          onLoad={api.skill}
          onSave={api.saveSkill}
          onShare={api.shareSkill}
          onChanged={loadBootstrap}
        />
      ) : null}
      {scheduleBot ? (
        <ScheduledTasks
          bot={scheduleBot}
          onClose={() => setScheduleBot(undefined)}
          onList={api.schedules}
          onSave={api.saveSchedule}
          onDelete={api.deleteSchedule}
          onRun={api.runSchedule}
          onTriggered={async () => {
            setMessages([]);
            setLoadingMessages(true);
            await loadMessages();
          }}
        />
      ) : null}
      {accountSettingsOpen ? (
        <AccountSettings
          demo={demo}
          onClose={() => setAccountSettingsOpen(false)}
          onOpenSkills={() => {
            setAccountSettingsOpen(false);
            setSkillLibraryOpen(true);
          }}
          onListShares={api.sharedLinks}
          onRevokeShare={api.revokeShare}
          onDeleteAccount={deleteAccount}
          onSignOut={signOut}
        />
      ) : null}
      <ActionSheet
        visible={botMenuOpen}
        title={selectedBot?.name ?? 'FroggyBot'}
        message="Schedule its work, share it, or manage this conversation."
        options={[
          { label: 'Scheduled tasks', onPress: () => setScheduleBot(selectedBot) },
          { label: 'Share bot setup', onPress: () => share('bot') },
          { label: 'Share conversation', onPress: () => share('chat') },
          { label: 'Clear conversation', destructive: true, onPress: () => setPendingBotAction('clear') },
          { label: 'Delete bot', destructive: true, onPress: () => setPendingBotAction('delete') },
        ]}
        onClose={() => setBotMenuOpen(false)}
      />
      <ActionSheet
        visible={Boolean(pendingBotAction)}
        title={pendingBotAction === 'delete' ? `Delete ${selectedBot?.name ?? 'this bot'}?` : 'Clear this conversation?'}
        message={
          pendingBotAction === 'delete'
            ? 'This permanently deletes the FroggyBot, its direct chat, and removes it from your groups.'
            : 'This permanently deletes every message in this direct chat but keeps the FroggyBot.'
        }
        options={[
          {
            label: pendingBotAction === 'delete' ? 'Delete bot' : 'Clear conversation',
            destructive: true,
            onPress: runBotDeletion,
          },
        ]}
        onClose={() => setPendingBotAction(undefined)}
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

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: '#FBFBF9' },
  shell: { flex: 1, flexDirection: 'row', overflow: 'hidden' },
  wideDrawer: { width: 290 },
  mobileDrawerLayer: { position: 'absolute', inset: 0, zIndex: 20, flexDirection: 'row' },
  backdrop: { position: 'absolute', inset: 0, backgroundColor: 'rgba(18,18,15,0.28)' },
  mobileDrawer: {
    height: '100%',
    backgroundColor: '#F2F1ED',
    ...Platform.select({
      web: { boxShadow: '8px 0 24px rgba(0,0,0,0.2)' },
      default: { shadowColor: '#000', shadowOpacity: 0.2, shadowRadius: 24, shadowOffset: { width: 8, height: 0 } },
    }),
  },
});
