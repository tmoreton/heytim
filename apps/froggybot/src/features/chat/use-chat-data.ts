import { useCallback, useEffect, useRef, useState } from 'react';

import type { FrogBotApi } from '@/lib/api';
import { chiefFirst } from '@/lib/bot-branding';
import type { Bootstrap, Bot, ConversationSelection, Group, Message } from '@/lib/types';

import {
  chooseAvailableSelection,
  isPendingMessage,
  isRefreshingMessage,
  reconcileBootstrap,
  reconcileMessages,
} from './chat-state';

const MESSAGE_REFRESH_MS = 900;
const CONVERSATION_REFRESH_MS = 1_200;

export function useChatData(api: FrogBotApi) {
  const bootstrapRequestId = useRef(0);
  const messageRequestId = useRef(0);
  const initialized = useRef(false);
  const [data, setData] = useState<Bootstrap>();
  const [selection, setSelection] = useState<ConversationSelection>();
  const [messages, setMessages] = useState<Message[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [error, setError] = useState('');

  const pending = messages.some(isPendingMessage);
  const refreshing = messages.some(isRefreshingMessage);

  const invalidateMessages = useCallback(() => {
    messageRequestId.current += 1;
  }, []);

  const openConversation = useCallback((next: ConversationSelection) => {
    invalidateMessages();
    setMessages([]);
    setLoadingMessages(true);
    setSelection(next);
  }, [invalidateMessages]);

  const readMessages = useCallback(async (target: ConversationSelection) => (
    target.kind === 'group' ? api.groupMessages(target.id) : api.messages(target.id)
  ), [api]);

  const loadMessagesFor = useCallback(async (target: ConversationSelection) => {
    const currentRequest = ++messageRequestId.current;
    try {
      const next = await readMessages(target);
      if (currentRequest === messageRequestId.current) {
        setMessages((current) => reconcileMessages(current, next));
        setError('');
      }
    } catch (value) {
      if (currentRequest === messageRequestId.current) {
        setError(value instanceof Error ? value.message : 'Could not load this conversation.');
      }
    } finally {
      if (currentRequest === messageRequestId.current) setLoadingMessages(false);
    }
  }, [readMessages]);

  const loadMessages = useCallback(async () => {
    if (selection) await loadMessagesFor(selection);
  }, [loadMessagesFor, selection]);

  const loadBootstrap = useCallback(async () => {
    const currentRequest = ++bootstrapRequestId.current;
    try {
      const next = await api.bootstrap();
      if (currentRequest !== bootstrapRequestId.current) return;
      const initialLoad = !initialized.current;
      initialized.current = true;
      setData((current) => reconcileBootstrap(current, next));
      setSelection((current) => chooseAvailableSelection(next, current));
      if (initialLoad) setLoadingMessages(Boolean(next.groups[0] ?? next.bots[0]));
      setError('');
    } catch (value) {
      if (currentRequest === bootstrapRequestId.current) {
        initialized.current = true;
        setError(value instanceof Error ? value.message : 'Could not load your bots.');
      }
    }
  }, [api]);

  const upsertBot = useCallback((saved: Bot, completeOnboarding = false) => {
    setData((current) => {
      if (!current) return current;
      const exists = current.bots.some((bot) => bot.id === saved.id);
      const bots = exists
        ? current.bots.map((bot) => (bot.id === saved.id ? saved : bot))
        : [saved, ...current.bots];
      return {
        ...current,
        bots: chiefFirst(bots),
        needsBotOnboarding: completeOnboarding ? false : current.needsBotOnboarding,
      };
    });
    openConversation({ kind: 'bot', id: saved.id });
  }, [openConversation]);

  const upsertGroup = useCallback((saved: Group) => {
    setData((current) => {
      if (!current) return current;
      const exists = current.groups.some((group) => group.id === saved.id);
      return {
        ...current,
        groups: exists
          ? current.groups.map((group) => (group.id === saved.id ? saved : group))
          : [saved, ...current.groups],
      };
    });
    openConversation({ kind: 'group', id: saved.id });
  }, [openConversation]);

  const replaceBootstrap = useCallback((next: Bootstrap, resetMessages = false) => {
    const nextSelection = chooseAvailableSelection(next, selection);
    setData((current) => reconcileBootstrap(current, next));
    if (resetMessages) {
      invalidateMessages();
      setMessages([]);
      setLoadingMessages(Boolean(nextSelection));
    }
    setSelection(nextSelection);
    setError('');
  }, [invalidateMessages, selection]);

  const refreshAfterMutation = useCallback(async () => {
    const next = await api.bootstrap();
    replaceBootstrap(next, true);
  }, [api, replaceBootstrap]);

  const clearMessages = useCallback((loading = false) => {
    invalidateMessages();
    setMessages([]);
    setLoadingMessages(loading);
  }, [invalidateMessages]);

  const markConversationProcessing = useCallback((
    target: ConversationSelection,
    processingBotName?: string,
  ) => {
    setData((current) => {
      if (!current) return current;
      if (target.kind === 'bot') {
        return {
          ...current,
          bots: current.bots.map((bot) => bot.id === target.id
            ? { ...bot, processing: true, processingBotName }
            : bot),
        };
      }
      return {
        ...current,
        groups: current.groups.map((group) => group.id === target.id
          ? { ...group, processing: true, processingBotName }
          : group),
      };
    });
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => void loadBootstrap(), 0);
    return () => {
      clearTimeout(timer);
      bootstrapRequestId.current += 1;
    };
  }, [loadBootstrap]);

  useEffect(() => {
    if (!selection) return;
    const timer = setTimeout(() => void loadMessagesFor(selection), 0);
    return () => {
      clearTimeout(timer);
      invalidateMessages();
    };
  }, [invalidateMessages, loadMessagesFor, selection]);

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

  const conversationProcessing = Boolean(
    data?.bots.some((bot) => bot.processing) || data?.groups.some((group) => group.processing),
  );
  useEffect(() => {
    if (!conversationProcessing) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      await loadBootstrap();
      if (active) timer = setTimeout(poll, CONVERSATION_REFRESH_MS);
    };
    timer = setTimeout(poll, CONVERSATION_REFRESH_MS);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [conversationProcessing, loadBootstrap]);

  return {
    data,
    selection,
    messages,
    loadingMessages,
    error,
    setError,
    pending,
    loadBootstrap,
    loadMessages,
    openConversation,
    upsertBot,
    upsertGroup,
    replaceBootstrap,
    refreshAfterMutation,
    clearMessages,
    markConversationProcessing,
  };
}
