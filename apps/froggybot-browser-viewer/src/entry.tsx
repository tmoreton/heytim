import { Component, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';

import { isLiveViewUrl, viewerViewport, VIEWER_CONNECT, VIEWER_READY } from '@froggybot/client';
import { installPrivateViewerStorage } from './memory-storage';

declare global {
  interface Window { ReactNativeWebView?: { postMessage: (value: string) => void } }
}

// This document is disposable: the SDK's module-level auth cache dies with the
// iframe/WebView. No tokens ever enter the main chat bundle or persistent storage.
const root = createRoot(document.getElementById('root')!);
const failure = 'The live browser could not connect. Use Refresh connection in FroggyBot.';
class ViewerBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <p role="alert">{failure}</p> : this.props.children; }
}

let used = false;
const connect = async (event: MessageEvent) => {
  if (event.origin !== window.location.origin || (event.source !== window.parent && event.source !== window)) return;
  if (used || event.data?.type !== VIEWER_CONNECT || !isLiveViewUrl(event.data?.signedUrl)) return;
  used = true;
  const signedUrl: string = event.data.signedUrl;
  const viewport = viewerViewport(event.data.viewport);
  try {
    installPrivateViewerStorage(window);
    // Third-party diagnostics can contain stream URLs. Silence only this
    // disposable document's console, never the parent application console.
    for (const method of ['debug', 'info', 'log', 'warn', 'error', 'trace'] as const) window.console[method] = () => {};
    const { BrowserLiveView } = await import('bedrock-agentcore/browser/live-view');
    root.render(<ViewerBoundary><BrowserLiveView signedUrl={signedUrl} remoteWidth={viewport.width} remoteHeight={viewport.height} /></ViewerBoundary>);
  } catch { root.render(<p role="alert">{failure}</p>); }
};

window.addEventListener('message', connect);
window.addEventListener('pagehide', () => { root.unmount(); window.removeEventListener('message', connect); }, { once: true });
window.addEventListener('unhandledrejection', (event) => {
  event.preventDefault();
  // A background request can fail while video/input remains usable. Do not tear
  // down a working stream because an optional client feature rejected a promise.
  const notice = document.getElementById('notice');
  if (notice) notice.textContent = 'The browser reported a connection issue. If the view is not responding, use Refresh connection.';
});
root.render(<p>Connecting to your bot’s browser… If the view stays blank, use Refresh connection.</p>);
window.ReactNativeWebView?.postMessage(VIEWER_READY);
