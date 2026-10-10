import { createRoot } from 'react-dom/client';
import { SessionViewer } from '../src/SessionViewer';
import type { DcvSDK } from '../src/connection';

let connects = 0, disconnects = 0;
const sdk: DcvSDK = {
  setLogHandler() {},
  authenticate(_url, callbacks) {
    callbacks.success({}, [{ sessionId: 'fixture', authToken: 'synthetic' }]);
  },
  async connect(config) {
    connects += 1;
    config.observers.firstFrame();
    return { disconnect() { disconnects += 1; } };
  },
};
const capability = 'https://bedrock-agentcore.us-east-1.amazonaws.com/browser-streams/aws.browser.v1/sessions/test/live-view?X-Amz-Signature='
  + 'a'.repeat(64) + '&X-Amz-Expires=300';
Object.assign(window, { receiver: {
  inject: () => window.heytimSetBrowserSession!(capability, 390, 780),
  metrics: () => ({ connects, disconnects }),
} });
// Native WebKit may inject before React's first effect. Preserve that request.
window.heytimSetBrowserSession!(capability, 390, 780);
createRoot(document.getElementById('root')!).render(<SessionViewer sdk={sdk} />);
