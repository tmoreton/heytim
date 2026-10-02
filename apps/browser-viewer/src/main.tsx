import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserLiveView } from 'bedrock-agentcore/browser/live-view';
import './viewer.css';

type Session = { signedUrl: string; width: number; height: number };

declare global {
  interface Window {
    heytimSetBrowserSession?: (signedUrl: string, width: number, height: number) => void;
  }
}

let receiveSession: ((signedUrl: string, width: number, height: number) => void) | null = null;
let pendingSession: [string, number, number] | null = null;
window.heytimSetBrowserSession = (signedUrl, width, height) => {
  if (receiveSession) receiveSession(signedUrl, width, height);
  else pendingSession = [signedUrl, width, height];
};

function validSession(signedUrl: string, width: number, height: number): Session | null {
  try {
    const url = new URL(signedUrl);
    if (url.protocol !== 'https:' || !url.hostname.endsWith('.amazonaws.com')
      || !url.pathname.includes('/browser-streams/') || !url.pathname.endsWith('/live-view')
      || !Number.isInteger(width) || !Number.isInteger(height)
      || width < 320 || width > 3840 || height < 320 || height > 2160) return null;
    return { signedUrl, width, height };
  } catch {
    return null;
  }
}

function Viewer() {
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    receiveSession = (signedUrl, width, height) => {
      const next = validSession(signedUrl, width, height);
      setError(next === null);
      setSession(next);
    };
    if (pendingSession) {
      receiveSession(...pendingSession);
      pendingSession = null;
    }
    return () => { receiveSession = null; };
  }, []);

  if (error) return <p role="alert">The browser stream could not be opened. Return to HeyTim and try again.</p>;
  if (!session) return <p>Connecting to your browser…</p>;
  return <BrowserLiveView signedUrl={session.signedUrl}
    remoteWidth={session.width} remoteHeight={session.height} />;
}

createRoot(document.getElementById('root')!).render(<Viewer />);
