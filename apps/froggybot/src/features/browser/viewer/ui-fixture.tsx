// Local-only browser-test fixture. Not imported by the Expo app or viewer entry.
import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import type { BrowserApi } from '@/lib/browser-api';
import type { Bot, BotBrowserState } from '@/lib/types';
import { BrowserHandoff } from '../browser-handoff';

const bot: Bot = { id: 'owned-test-bot', name: 'Test Engineer', tagline: '', color: '#007A3D', prompt: '', toolIds: ['browser'], skillIds: [], createdAt: '', updatedAt: '', lastMessage: '', lastMessageAt: '' };
let state: BotBrowserState = { botId: bot.id, status: 'closed', contextLabel: 'Test Engineer · Private direct chat', hasSavedLogin: true };
const counters = { opens: 0, resumes: 0, closes: 0, forgets: 0, refreshed: 0, consent: false };
let mode = 'normal';
const emit = () => { document.getElementById('counters')!.textContent = JSON.stringify(counters); };
const api: BrowserApi = {
  browserStatus: async () => ({ ...state }),
  openBrowser: async () => {
    counters.opens++; emit();
    if (mode === 'busy') throw Object.assign(new Error('Busy'), { status: 409 });
    state = { ...state, status: 'human_control', resumedTurnId: undefined };
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
  return <SafeAreaProvider initialMetrics={{ frame: { x: 0, y: 0, width: 1200, height: 900 }, insets: { top: 0, left: 0, right: 0, bottom: 0 } }}>
    <h1>Browser handoff local test — no remote browser</h1>
    <label>Scenario <select aria-label="Scenario" onChange={(event) => { mode = event.target.value; }}><option>normal</option><option>busy</option><option>expiry</option><option>saving</option><option>uncertain</option></select></label>
    <button onClick={() => setHasTool(false)}>Remove browser capability</button>
    <button onClick={() => setVisible(true)}>Browser connection</button>
    <pre id="counters" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(counters)}</pre>
    <BrowserHandoff api={api} bot={{ ...bot, toolIds: hasTool ? ['browser'] : [] }} active={false} visible={visible} onOpen={() => setVisible(true)} onClose={() => setVisible(false)} onResumed={async () => { counters.refreshed++; emit(); }} />
  </SafeAreaProvider>;
}

createRoot(document.getElementById('root')!).render(<Fixture />);
