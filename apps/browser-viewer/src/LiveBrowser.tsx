import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { connectLiveView, type DcvSDK, type Phase, type Session } from './connection';

declare global {
  interface Window {
    webkit?: { messageHandlers?: {
      heytimBrowserStatus?: { postMessage(message: { state?: Phase; action?: 'reconnect' }): void };
    } };
  }
}

const messages: Record<Phase, string> = {
  connecting: 'Connecting to your secure browser…',
  connected: 'Live browser connected',
  failed: 'Couldn’t connect to your browser.',
  disconnected: 'The live browser disconnected.',
  timeout: 'The live browser is taking longer than expected.',
};

export function LiveBrowser({ sdk, session }: { sdk: DcvSDK; session: Session }) {
  const id = 'dcv-' + useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const { signedUrl, width, height } = session;
  const container = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<Phase>('connecting');
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [remote, setRemote] = useState({ width: session.width, height: session.height });
  useLayoutEffect(() => {
    const node = container.current;
    if (!node) return;
    const bounds = node.getBoundingClientRect();
    setSize({ width: bounds.width, height: bounds.height });
    const observer = new ResizeObserver(([entry]) => {
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  useEffect(() => connectLiveView(sdk, { signedUrl, width, height }, id, window.location.origin, next => {
    setPhase(next);
    window.webkit?.messageHandlers?.heytimBrowserStatus?.postMessage({ state: next });
  }, (width, height) => setRemote({ width, height })),
  [sdk, signedUrl, width, height, id]);

  const scale = Math.min(size.width / remote.width, size.height / remote.height);
  const failed = phase !== 'connecting' && phase !== 'connected';
  const reconnect = () => {
    window.webkit?.messageHandlers?.heytimBrowserStatus?.postMessage({ action: 'reconnect' });
  };
  return <div className="viewer-shell" ref={container} data-browser-phase={phase}>
    <div id={id} className="viewer-display" role="application" aria-label="Interactive remote browser"
      tabIndex={0} style={{
        width: remote.width, height: remote.height, transform: 'scale(' + scale + ')',
        left: Math.max(0, (size.width - remote.width * scale) / 2),
        top: Math.max(0, (size.height - remote.height * scale) / 2),
      }} />
    {phase === 'connected'
      ? <span className="sr-only" role="status">{messages[phase]}</span>
      : <div className="viewer-status" role={failed ? 'alert' : 'status'}>
        {!failed && <span className="spinner" aria-hidden="true" />}
        <p>{messages[phase]}</p>
        {failed && <>
          <p className="viewer-help">Your remote page is kept. Reconnect to continue.</p>
          {window.webkit?.messageHandlers?.heytimBrowserStatus
            ? <button type="button" onClick={reconnect}>Reconnect Live View</button>
            : <p className="viewer-help">Return to HeyTim and choose Reconnect Live View.</p>}
        </>}
      </div>}
  </div>;
}
