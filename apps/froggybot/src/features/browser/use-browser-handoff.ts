import { useEffect, useRef, useState } from 'react';

import type { BrowserApi } from '@/lib/browser-api';
import type { BotBrowserOpenOptions, BotBrowserState } from '@/lib/types';

import { browserError, isLiveViewUrl, liveViewDeadline, withoutLiveView } from './browser-policy';
import { resumeBrowserWithProfilePolling } from './resume-browser';

export function useBrowserHandoff(api: BrowserApi, botId: string, onResumed: () => Promise<void>, onDismiss: () => void,
  options: BotBrowserOpenOptions = {}, autoOpen = false) {
  const [state, setState] = useState<BotBrowserState>();
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [rememberLogin, setRememberLogin] = useState(false);
  const [expired, setExpired] = useState(false);
  const [pendingConsent, setPendingConsent] = useState<boolean>();
  const [confirmation, setConfirmation] = useState<'disconnect' | 'forget'>();
  const locked = useRef(false);
  const mounted = useRef(true);
  const pendingUrl = useRef(options.url);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  const accept = (next: BotBrowserState, allowLiveView = false) => {
    if (next.botId !== botId || next.groupId) throw new Error('Browser context mismatch');
    if (mounted.current) setState(allowLiveView ? next : withoutLiveView(next));
    return next;
  };

  const run = async (action: 'open' | 'resume' | 'close' | 'forget' | 'status', task: () => Promise<void>) => {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError('');
    try { await task(); }
    catch (value) {
      if (mounted.current) setError(browserError(value, action));
      // A lost response is not evidence that a mutation failed. Reconcile; never auto-repeat it.
      try { accept(await api.browserStatus({ botId })); } catch { /* Keep the safe error, never a URL-bearing provider error. */ }
    } finally {
      locked.current = false;
      if (mounted.current) setBusy(false);
    }
  };

  const open = (requested: BotBrowserOpenOptions = {}) => run('open', async () => {
    setPendingConsent(undefined);
    setExpired(false);
    setState((previous) => previous ? withoutLiveView(previous) : undefined);
    const url = requested.url ?? pendingUrl.current;
    // Consume on the first attempt, including a manual open after an active run.
    // An uncertain response must never cause Refresh to repeat navigation.
    pendingUrl.current = undefined;
    let next: BotBrowserState;
    try {
      next = await api.openBrowser({ botId }, { display: state?.display ?? options.display, ...requested, url });
    } catch (value) {
      if (value && typeof value === 'object' && 'status' in value && value.status === 409) pendingUrl.current = url;
      throw value;
    }
    if (next.status === 'human_control') {
      if (!isLiveViewUrl(next.liveViewUrl) || liveViewDeadline(next) <= Date.now()) {
        accept(next);
        throw new Error('Invalid or expired Live View connection');
      }
      accept(next, true);
    } else accept(next);
  });

  // One auto-open per mounted dialog. Refresh never replays the clicked URL.
  const initial = useRef({ api, botId, open, options, autoOpen });
  useEffect(() => {
    let current = true;
    const { api, botId, open, options, autoOpen } = initial.current;
    locked.current = true;
    api.browserStatus({ botId }).then(async (next) => {
      if (next.botId !== botId || next.groupId) throw new Error('Browser context mismatch');
      if (!current) return;
      setState(withoutLiveView(next));
      if (autoOpen && next.status !== 'resuming' && next.status !== 'opening') {
        locked.current = false;
        await open(options);
      }
    }).catch((value) => { if (current) setError(browserError(value, 'status')); })
      .finally(() => { if (current) { locked.current = false; setBusy(false); } });
    return () => { current = false; };
  }, []);

  const resume = () => run('resume', async () => {
    setState((previous) => previous ? withoutLiveView(previous) : undefined);
    const consent = pendingConsent ?? rememberLogin;
    setPendingConsent(consent);
    const next = await resumeBrowserWithProfilePolling({ api, botId, rememberLogin: consent,
      onState: (value) => { accept(value); }, isActive: () => mounted.current });
    if (!mounted.current || !next) return;
    if (next.status === 'resuming' && !next.resumedTurnId) {
      setError('Your login is still being saved. The bot has not resumed. Choose Continue handoff to check again, or Disconnect to end the session.');
      return;
    }
    if (next.status !== 'ready' || !next.resumedTurnId) throw new Error('Handoff not confirmed');
    // Refresh separately: a chat refresh failure must never invite a duplicate resume request.
    try { await onResumed(); } catch { /* Existing chat polling will reconcile the accepted turn. */ }
    if (mounted.current) onDismiss();
  });

  const disconnect = () => run('close', async () => {
    setConfirmation(undefined);
    setState((previous) => previous ? withoutLiveView(previous) : undefined);
    const next = accept(await api.closeBrowser({ botId }));
    if (next.status !== 'closed' && next.status !== 'expired') throw new Error('Browser not closed');
    if (mounted.current) onDismiss();
  });

  const forget = () => run('forget', async () => {
    setConfirmation(undefined);
    setRememberLogin(false);
    setState((previous) => previous ? withoutLiveView(previous) : undefined);
    accept(await api.forgetBrowserLogin({ botId }));
  });

  const requestClose = () => {
    if (busy) return;
    if (!state || state.status === 'closed' || state.status === 'expired' || (state.status === 'ready' && state.resumedTurnId)) {
      setState((previous) => previous ? withoutLiveView(previous) : undefined);
      onDismiss();
    } else setConfirmation('disconnect');
  };

  useEffect(() => {
    if (!state?.liveViewUrl) return;
    const deadline = liveViewDeadline(state);
    const timeout = setTimeout(() => {
      setExpired(true);
      setState((previous) => previous ? withoutLiveView(previous) : undefined);
    }, Math.max(0, deadline - Date.now()));
    return () => clearTimeout(timeout);
  }, [state]);

  return { state, busy, error, rememberLogin, expired, confirmation, pendingConsent, setRememberLogin, setConfirmation,
    open, resume, disconnect, forget, requestClose,
    refreshStatus: () => run('status', async () => { accept(await api.browserStatus({ botId })); }),
  };
}
