import { useEffect, useRef, useState } from 'react';

import type { BrowserApi } from '@/lib/browser-api';
import type { BotBrowserState } from '@/lib/types';

import { browserError, isLiveViewUrl, liveViewDeadline, withoutLiveView } from './browser-policy';
import { resumeBrowserWithProfilePolling } from './resume-browser';

export function useBrowserHandoff(api: BrowserApi, botId: string, onResumed: () => Promise<void>, onDismiss: () => void) {
  const [state, setState] = useState<BotBrowserState>();
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [rememberLogin, setRememberLogin] = useState(false);
  const [expired, setExpired] = useState(false);
  const [pendingConsent, setPendingConsent] = useState<boolean>();
  const [confirmation, setConfirmation] = useState<'disconnect' | 'forget'>();
  const locked = useRef(false);
  const mounted = useRef(true);
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

  const open = () => run('open', async () => {
    setPendingConsent(undefined);
    setExpired(false);
    setState((previous) => previous ? withoutLiveView(previous) : undefined);
    const next = await api.openBrowser({ botId });
    if (next.status === 'human_control') {
      if (!isLiveViewUrl(next.liveViewUrl) || liveViewDeadline(next) <= Date.now()) {
        accept(next);
        throw new Error('Invalid or expired Live View connection');
      }
      accept(next, true);
    } else accept(next);
  });

  useEffect(() => {
    let current = true;
    locked.current = true;
    api.browserStatus({ botId }).then((next) => {
      if (next.botId !== botId || next.groupId) throw new Error('Browser context mismatch');
      if (current) setState(withoutLiveView(next));
    }).catch((value) => { if (current) setError(browserError(value, 'status')); })
      .finally(() => { if (current) { locked.current = false; setBusy(false); } });
    return () => { current = false; };
  }, [api, botId]);

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
    if (!state || state.status === 'closed' || state.status === 'expired' || state.resumedTurnId) {
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
