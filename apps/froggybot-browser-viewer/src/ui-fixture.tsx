// Local-only browser-test fixture. Not imported by the Expo app or viewer entry.
import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiClientError, browserViewports, type BrowserApi } from '@froggybot/client';
import type { Bot, BotBrowserState } from '@froggybot/contracts';
import { BrowserHandoff } from '../../froggybot/src/features/browser/browser-handoff';
import { MessageMarkdown } from '../../froggybot/src/components/message-markdown';

const bot: Bot = { id: 'owned-test-bot', name: 'Test Engineer', tagline: '', color: '#007A3D', prompt: '', toolIds: ['browser'], skillIds: [], createdAt: '', updatedAt: '', lastMessage: '', lastMessageAt: '' };
let state: BotBrowserState = { botId: bot.id, status: 'closed', contextLabel: 'Test Engineer · Private direct chat', hasSavedLogin: true };
const counters = { opens: 0, resumes: 0, closes: 0, forgets: 0, refreshed: 0, consent: false, url: '', display: '' };
let mode = 'normal';
const emit = () => { document.getElementById('counters')!.textContent = JSON.stringify(counters); };
const api: BrowserApi = {
  browserStatus: async () => ({ ...state }),
  openBrowser: async (_context, options) => {
    counters.url = options?.url ?? ''; counters.display = options?.display ?? 'desktop';
    counters.opens++; emit();
    if (mode === 'busy') throw new ApiClientError(409, 'browser_bot_busy', 'Provider detail hidden from the UI');
    const display = options?.display ?? 'desktop';
    state = { ...state, status: 'human_control', resumedTurnId: undefined, display, viewport: browserViewports[display], mobileSiteSupported: true };
    return { ...state,
      liveViewUrl: 'https://bedrock-agentcore.us-east-1.amazonaws.com/browser-streams/aws.browser.v1/sessions/test/live-view?X-Amz-Signature=TEST-ONLY-NOT-A-CREDENTIAL',
      liveViewExpiresAt: new Date(Date.now() + (mode === 'expiry' ? 1500 : 300_000)).toISOString(),
    };
  },
  resumeBrowser: async (_context, consent) => {
    counters.resumes++; counters.consent = consent; emit();
    if (mode === 'uncertain') { state = { ...state, status: 'resuming' }; throw new Error('Uncertain response'); }
    if (mode === 'saving' && counters.resumes < 3) return (state = { ...state, status: 'resuming' });
    return (state = { ...state, status: 'ready', resumedTurnId: 'one-scoped-turn' });
  },
  closeBrowser: async () => { counters.closes++; emit(); return (state = { ...state, status: 'closed' }); },
  forgetBrowserLogin: async () => { counters.forgets++; emit(); return (state = { ...state, status: 'closed', hasSavedLogin: false }); },
};

function Fixture() {
  const [visible, setVisible] = useState(false);
  const [hasTool, setHasTool] = useState(true);
  const [url, setUrl] = useState<string>();
  const [active, setActive] = useState(false);
  useEffect(() => {
    if (!visible || !active) return;
    const timer = setTimeout(() => setActive(false), 1500);
    return () => clearTimeout(timer);
  }, [visible, active]);
  return <SafeAreaProvider initialMetrics={{ frame: { x: 0, y: 0, width: 1200, height: 900 }, insets: { top: 0, left: 0, right: 0, bottom: 0 } }}>
    <h1>Browser handoff local test — no remote browser</h1>
    <label>Scenario <select aria-label="Scenario" onChange={(event) => {
      mode = event.target.value; setActive(mode === 'active');
      if (mode === 'failed') state = { ...state, status: 'opening', recoveryRequired: true, resumedTurnId: 'old-turn' };
      if (mode === 'ended') state = { ...state, status: 'expired' };
    }}><option>normal</option><option>busy</option><option>expiry</option><option>saving</option><option>uncertain</option><option>active</option><option>failed</option><option>ended</option></select></label>
    <button onClick={() => setHasTool(false)}>Remove browser capability</button>
    <button onClick={() => setVisible(true)}>Browser connection</button>
    <MessageMarkdown onOpenLink={(link) => { setUrl(link); setVisible(true); }}>{'[Open example](https://example.com/chat-link)'}</MessageMarkdown>
    <pre id="counters" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(counters)}</pre>
    <BrowserHandoff api={api} bot={{ ...bot, toolIds: hasTool ? ['browser'] : [] }} active={active} initialUrl={url} visible={visible} onClose={() => { setVisible(false); setUrl(undefined); }} onResumed={async () => { counters.refreshed++; emit(); }} />
  </SafeAreaProvider>;
}

createRoot(document.getElementById('root')!).render(<StrictMode><Fixture /></StrictMode>);
