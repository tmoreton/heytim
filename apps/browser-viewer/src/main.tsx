import { useEffect, useRef, useState } from 'react';
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
  const [rendered, setRendered] = useState(false);
  const [slow, setSlow] = useState(false);
  const viewRef = useRef<HTMLDivElement>(null);
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

  useEffect(() => {
    if (!session) return;
    const view = viewRef.current;
    if (!view) return;
    setRendered(false);
    setSlow(false);
    const observer = new MutationObserver(() => setRendered(view.childElementCount > 0));
    observer.observe(view, { childList: true });
    const timer = window.setTimeout(() => setSlow(true), 20000);
    setRendered(view.childElementCount > 0);
    return () => {
      observer.disconnect();
      window.clearTimeout(timer);
    };
  }, [session?.signedUrl]);

  if (error) return <p role="alert">The browser stream could not be opened. Return to HeyTim and try again.</p>;
  if (!session) return <p>Connecting to your browser…</p>;
  return <div className="viewer-shell">
    <div className="viewer-stream" ref={viewRef}>
      <BrowserLiveView key={session.signedUrl} signedUrl={session.signedUrl}
        remoteWidth={session.width} remoteHeight={session.height} />
    </div>
    {!rendered && <p className="viewer-status" role={slow ? 'alert' : 'status'}>
      {slow
        ? 'The live browser is taking longer than expected. Return to HeyTim and tap Reconnect Live View.'
        : 'Connecting to the live browser…'}
    </p>}
  </div>;
}

createRoot(document.getElementById('root')!).render(<Viewer />);
