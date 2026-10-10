// Development-only fixture; Vite's production entry does not include this file.
import { createRoot } from 'react-dom/client';
import { LiveBrowser } from '../src/LiveBrowser';
import type { DcvSDK, ConnectionConfig } from '../src/connection';
import '../src/viewer.css';

let auth: Parameters<DcvSDK['authenticate']>[1];
let config: ConnectionConfig;
let connects = 0, disconnects = 0, clicks = 0, generation = 0;
const bridge: unknown[] = [];
window.webkit = { messageHandlers: { heytimBrowserStatus: { postMessage: value => bridge.push(value) } } };
const sdk: DcvSDK = {
  setLogHandler() {},
  authenticate(_url, callbacks) { auth = callbacks; },
  async connect(value) {
    config = value;
    connects += 1;
    const node = document.getElementById(value.divId)!;
    node.innerHTML = '<label style="position:absolute;left:20px;top:20px">Remote input <input aria-label="Remote input"></label>'
      + '<button style="position:absolute;left:40%;top:45%">Remote action</button>';
    node.querySelector('button')!.onclick = () => { clicks += 1; };
    return { disconnect() { disconnects += 1; node.replaceChildren(); } };
  },
};
const root = createRoot(document.getElementById('root')!);
function render(width = 1440, height = 900) {
  generation += 1;
  const signedUrl = 'https://bedrock-agentcore.us-east-1.amazonaws.com/browser-streams/aws.browser.v1/sessions/test/live-view?X-Amz-Signature='
    + generation.toString(16).padStart(64, '0') + '&X-Amz-Expires=300';
  root.render(<LiveBrowser key={generation} sdk={sdk} session={{ signedUrl, width, height }} />);
}
Object.assign(window, { fixture: {
  render,
  authenticate: () => auth.success({}, [{ sessionId: 'test-session', authToken: 'synthetic' }]),
  fail: () => auth.error(),
  frame: () => config.observers.firstFrame(),
  disconnect: () => config.observers.disconnect(),
  layout: (width: number, height: number) => config.observers.displayLayout(width, height),
  metrics: () => ({ connects, disconnects, clicks, bridge }),
  close: () => root.render(null),
} });
render();
