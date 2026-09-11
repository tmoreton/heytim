import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';

import type { FrogBotApi } from '@/lib/api';
import { chiefFirst } from '@/lib/bot-branding';
import type { Bootstrap, Bot, ConversationSelection, Group, Message } from '@/lib/types';

import {
  chooseAvailableSelection,
  isPendingMessage,
  isRefreshingMessage,
  mergeEarlierMessages,
  mergeLatestMessages,
  reconcileBootstrap,
  reconcileMessages,
} from './chat-state';
import { nextPollingDelay } from './polling';

const MESSAGE_REFRESH_MS = 900;
const CONVERSATION_REFRESH_MS = 1_200;

export function useChatData(api: FrogBotApi) {
  const bootstrapRequestId = useRef(0);
  const messageRequestId = useRef(0);
  const historyRequestId = useRef(0);
  const firstMessagePageLoaded = useRef(false);
  const initialized = useRef(false);
  const [data, setData] = useState<Bootstrap>();
  const [selection, setSelection] = useState<ConversationSelection>();
  const [messages, setMessages] = useState<Message[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [loadingEarlierMessages, setLoadingEarlierMessages] = useState(false);
  const [nextMessageToken, setNextMessageToken] = useState<string>();
  const [appActive, setAppActive] = useState(
    AppState.currentState === null || AppState.currentState === 'active',
  );
  const [error, setError] = useState('');

  const pending = messages.some(isPendingMessage);
  const refreshing = messages.some(isRefreshingMessage);

  const invalidateMessages = useCallback(() => {
    messageRequestId.current += 1;
    historyRequestId.current += 1;
    setLoadingEarlierMessages(false);
  }, []);

  const openConversation = useCallback((next: ConversationSelection) => {
    invalidateMessages();
    setMessages([]);
    setNextMessageToken(undefined);
    setLoadingMessages(true);
    setSelection(next);
  }, [invalidateMessages]);

  const readMessages = useCallback(async (target: ConversationSelection, cursor?: string) => (
    target.kind === 'group' ? api.groupMessages(target.id, cursor) : api.messages(target.id, cursor)
  ), [api]);

  const loadMessagesFor = useCallback(async (target: ConversationSelection): Promise<boolean> => {
    const currentRequest = ++messageRequestId.current;
    const isFirstPage = !firstMessagePageLoaded.current;
    try {
      const next = await readMessages(target);
      if (currentRequest === messageRequestId.current) {
        setMessages((current) => next.nextToken
          ? mergeLatestMessages(current, next.messages)
          : reconcileMessages(current, next.messages));
        setNextMessageToken((current) => (
          isFirstPage || !next.nextToken ? next.nextToken : current
        ));
        firstMessagePageLoaded.current = true;
        setError('');
      }
      return true;
    } catch (value) {
      if (currentRequest === messageRequestId.current) {
        setError(value instanceof Error ? value.message : 'Could not load this conversation.');
      }
      return false;
    } finally {
      if (currentRequest === messageRequestId.current) setLoadingMessages(false);
    }
  }, [readMessages]);

  const loadMessages = useCallback(async () => {
    return selection ? loadMessagesFor(selection) : true;
  }, [loadMessagesFor, selection]);

  const loadEarlierMessages = useCallback(async () => {
    if (!selection || !nextMessageToken || loadingEarlierMessages) return;
    const target = selection;
    const cursor = nextMessageToken;
    const currentRequest = ++historyRequestId.current;
    setLoadingEarlierMessages(true);
    try {
      const page = await readMessages(target, cursor);
      if (currentRequest !== historyRequestId.current) return;
      setMessages((current) => mergeEarlierMessages(current, page.messages));
      setNextMessageToken(page.nextToken);
      setError('');
    } catch (value) {
      if (currentRequest === historyRequestId.current) {
        setError(value instanceof Error ? value.message : 'Could not load earlier messages.');
      }
    } finally {
      if (currentRequest === historyRequestId.current) setLoadingEarlierMessages(false);
    }
  }, [loadingEarlierMessages, nextMessageToken, readMessages, selection]);

  const loadBootstrap = useCallback(async (): Promise<boolean> => {
    const currentRequest = ++bootstrapRequestId.current;
    try {
      const next = await api.bootstrap();
      if (currentRequest !== bootstrapRequestId.current) return true;
      const initialLoad = !initialized.current;
      initialized.current = true;
      setData((current) => reconcileBootstrap(current, next));
      setSelection((current) => chooseAvailableSelection(next, current));
      if (initialLoad) setLoadingMessages(Boolean(next.groups[0] ?? next.bots[0]));
      setError('');
      return true;
    } catch (value) {
      if (currentRequest === bootstrapRequestId.current) {
        initialized.current = true;
        setError(value instanceof Error ? value.message : 'Could not load your bots.');
      }
      return false;
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
      setNextMessageToken(undefined);
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
    setNextMessageToken(undefined);
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
    const subscription = AppState.addEventListener('change', (state) => {
      setAppActive(state === 'active');
    });
    return () => subscription.remove();
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
    firstMessagePageLoaded.current = false;
    const timer = setTimeout(() => void loadMessagesFor(selection), 0);
    return () => {
      clearTimeout(timer);
      invalidateMessages();
    };
  }, [invalidateMessages, loadMessagesFor, selection]);

  useEffect(() => {
    if (!refreshing || !appActive) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    let failures = 0;
    const poll = async () => {
      const succeeded = await loadMessages();
      failures = succeeded ? 0 : failures + 1;
      if (active) timer = setTimeout(poll, nextPollingDelay(MESSAGE_REFRESH_MS, failures));
    };
    timer = setTimeout(poll, MESSAGE_REFRESH_MS);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [appActive, loadMessages, refreshing]);

  const conversationProcessing = Boolean(
    data?.bots.some((bot) => bot.processing) || data?.groups.some((group) => group.processing),
  );
  useEffect(() => {
    if (!conversationProcessing || !appActive) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    let failures = 0;
    const poll = async () => {
      const succeeded = await loadBootstrap();
      failures = succeeded ? 0 : failures + 1;
      if (active) timer = setTimeout(poll, nextPollingDelay(CONVERSATION_REFRESH_MS, failures));
    };
    timer = setTimeout(poll, CONVERSATION_REFRESH_MS);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [appActive, conversationProcessing, loadBootstrap]);

  const refreshBootstrap = useCallback(async () => {
    await loadBootstrap();
  }, [loadBootstrap]);

  return {
    data,
    selection,
    messages,
    loadingMessages,
    loadingEarlierMessages,
    hasEarlierMessages: Boolean(nextMessageToken),
    error,
    setError,
    pending,
    loadBootstrap: refreshBootstrap,
    loadMessages,
    loadEarlierMessages,
    openConversation,
    upsertBot,
    upsertGroup,
    replaceBootstrap,
    refreshAfterMutation,
    clearMessages,
    markConversationProcessing,
  };
}
