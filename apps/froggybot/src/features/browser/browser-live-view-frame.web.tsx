import { useRef } from 'react';

import { viewerLocation, VIEWER_CONNECT } from '@froggybot/client';
import type { BotBrowserState } from '@froggybot/contracts';

export default function BrowserLiveViewFrame({ signedUrl, viewport }: { signedUrl: string; viewport?: BotBrowserState['viewport'] }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const origin = window.location.origin;
  return <iframe
    ref={frame}
    title="Private bot browser — sign in here"
    src={viewerLocation(origin)}
    referrerPolicy="no-referrer"
    sandbox="allow-scripts allow-same-origin"
    onLoad={() => frame.current?.contentWindow?.postMessage({ type: VIEWER_CONNECT, signedUrl, viewport }, origin)}
    style={{ width: '100%', height: '100%', border: 0, background: '#E9EEEA' }}
  />;
}
