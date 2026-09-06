import { useCallback, useEffect, useRef, useState } from 'react';

import type { FrogBotApi } from '@/lib/api';
import type { Bootstrap, Message } from '@/lib/types';

import type { ConversationSelection } from './conversation-drawer';

const MESSAGE_REFRESH_MS = 900;
const REFRESHING_STATUSES = new Set<Message['status']>(['pending', 'running', 'waiting']);
const PENDING_STATUSES = new Set<Message['status']>([
  ...REFRESHING_STATUSES,
  'needs_input',
  'awaiting_approval',
]);

export function useChatData(api: FrogBotApi) {
  const requestId = useRef(0);
  const [data, setData] = useState<Bootstrap>();
  const [selection, setSelection] = useState<ConversationSelection>();
  const [messages, setMessages] = useState<Message[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [error, setError] = useState('');

  const pending = messages.some((message) => PENDING_STATUSES.has(message.status));
  const refreshing = messages.some((message) => REFRESHING_STATUSES.has(message.status));

  const chooseAvailableSelection = useCallback((next: Bootstrap, current?: ConversationSelection) => {
    if (current?.kind === 'bot' && next.bots.some((bot) => bot.id === current.id)) return current;
    if (current?.kind === 'group' && next.groups.some((group) => group.id === current.id)) return current;
    if (next.groups[0]) return { kind: 'group' as const, id: next.groups[0].id };
    if (next.bots[0]) return { kind: 'bot' as const, id: next.bots[0].id };
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

  const openConversation = useCallback((next: ConversationSelection) => {
    setMessages([]);
    setLoadingMessages(true);
    setSelection(next);
  }, []);

  const invalidateMessages = useCallback(() => {
    requestId.current += 1;
  }, []);

  const loadMessages = useCallback(async () => {
    if (!selection) return;
    const currentRequest = ++requestId.current;
    try {
      const next = selection.kind === 'group'
        ? await api.groupMessages(selection.id)
        : await api.messages(selection.id);
      if (currentRequest === requestId.current) {
        setMessages(next);
        setError('');
      }
    } catch (value) {
      if (currentRequest === requestId.current) {
        setError(value instanceof Error ? value.message : 'Could not load this conversation.');
      }
    } finally {
      if (currentRequest === requestId.current) setLoadingMessages(false);
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
    const currentRequest = ++requestId.current;
    const request = selection.kind === 'group'
      ? api.groupMessages(selection.id)
      : api.messages(selection.id);
    request
      .then((next) => {
        if (!active || currentRequest !== requestId.current) return;
        setMessages(next);
        setError('');
      })
      .catch((value) => {
        if (active && currentRequest === requestId.current) {
          setError(value instanceof Error ? value.message : 'Could not load this conversation.');
        }
      })
      .finally(() => {
        if (active && currentRequest === requestId.current) setLoadingMessages(false);
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

  return {
    data,
    setData,
    selection,
    setSelection,
    messages,
    setMessages,
    loadingMessages,
    setLoadingMessages,
    error,
    setError,
    pending,
    chooseAvailableSelection,
    loadBootstrap,
    loadMessages,
    openConversation,
    invalidateMessages,
  };
}
