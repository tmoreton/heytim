export const VIEWER_PATH = '/bot-browser/index.html';

/** Native loads our own viewer shell, never the target website or a signed URL. */
export function viewerLocation(origin: string): string {
  const url = new URL(origin);
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if ((url.protocol !== 'https:' && !(local && url.protocol === 'http:')) || url.username || url.password || url.search || url.hash) {
    throw new Error('A secure browser viewer origin is required.');
  }
  return `${url.origin}${VIEWER_PATH}`;
}

export const VIEWER_READY = 'frogbot-browser-viewer-ready';
export const VIEWER_CONNECT = 'frogbot-browser-viewer-connect';
