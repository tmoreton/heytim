import { useEffect, useState } from 'react';
import { LiveBrowser } from './LiveBrowser';
import { type DcvSDK, validSession, type Session } from './connection';
import './viewer.css';

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

export function SessionViewer({ sdk }: { sdk: DcvSDK }) {
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    receiveSession = (signedUrl, width, height) => {
      const next = validSession(signedUrl, width, height);
      setError(next === null);
      setSession(next);
      setRevision(value => value + 1);
    };
    if (pendingSession) {
      receiveSession(...pendingSession);
      pendingSession = null;
    }
    return () => { receiveSession = null; };
  }, []);

  if (error) return <p role="alert">The browser stream could not be opened. Return to HeyTim and try again.</p>;
  if (!session) return <p>Connecting to your browser…</p>;
  return <LiveBrowser key={revision} sdk={sdk} session={session} />;
}
