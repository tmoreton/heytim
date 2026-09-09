import { useRef } from 'react';

import { viewerLocation, VIEWER_CONNECT } from './viewer-location';

export default function BrowserLiveViewFrame({ signedUrl }: { signedUrl: string }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const origin = window.location.origin;
  return <iframe
    ref={frame}
    title="Private bot browser — sign in here"
    src={viewerLocation(origin)}
    referrerPolicy="no-referrer"
    sandbox="allow-scripts allow-same-origin"
    onLoad={() => frame.current?.contentWindow?.postMessage({ type: VIEWER_CONNECT, signedUrl }, origin)}
    style={{ width: '100%', height: '100%', border: 0, background: '#E9EEEA' }}
  />;
}
