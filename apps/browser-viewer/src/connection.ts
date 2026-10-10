export type Session = { signedUrl: string; width: number; height: number };
export type Phase = 'connecting' | 'connected' | 'failed' | 'disconnected' | 'timeout';
export type Connection = { disconnect(): void };
type Authentication = { sessionId?: string; authToken?: string };
export type ConnectionConfig = {
  url: string; sessionId: string; authToken: string; divId: string; baseUrl: string;
  clipboardAutoSync: boolean;
  observers: {
    httpExtraSearchParams(): URLSearchParams;
    firstFrame(): void;
    disconnect(): void;
    displayLayout(width: number, height: number): void;
  };
};
export type DcvSDK = {
  setLogHandler(handler: () => void): void;
  authenticate(url: string, callbacks: {
    promptCredentials(): void;
    error(): void;
    success(authentication: unknown, sessions: Authentication[]): void;
    httpExtraSearchParams(): URLSearchParams;
  }): unknown;
  connect(config: ConnectionConfig): Promise<Connection>;
};

export function validSession(signedUrl: string, width: number, height: number): Session | null {
  try {
    const url = new URL(signedUrl);
    const expires = Number(url.searchParams.get('X-Amz-Expires'));
    const hasUserInfo = url.username.length > 0 || url.password.length > 0;
    if (hasUserInfo) return null;
    if (url.protocol !== 'https:' || url.port
      || !/^bedrock-agentcore\.[a-z0-9-]+\.amazonaws\.com$/.test(url.hostname)
      || !/^\/browser-streams\/aws\.browser\.v1\/sessions\/[A-Za-z0-9_-]+\/live-view$/.test(url.pathname)
      || !/^[a-f0-9]{64}$/i.test(url.searchParams.get('X-Amz-Signature') ?? '')
      || !Number.isInteger(expires) || expires < 1 || expires > 300
      || !Number.isInteger(width) || !Number.isInteger(height)
      || width < 320 || width > 3840 || height < 320 || height > 2160) return null;
    return { signedUrl, width, height };
  } catch {
    return null;
  }
}

/** A viewer connection owns no remote session, saved profile, or continuation. */
export function connectLiveView(
  sdk: DcvSDK, session: Session, divId: string, origin: string,
  onPhase: (phase: Phase) => void,
  onLayout: (width: number, height: number) => void,
  timeoutMs = 20_000,
): () => void {
  let ended = false;
  let connecting = false;
  let connection: Connection | undefined;
  const disconnect = () => {
    try { connection?.disconnect(); } catch { /* No provider details enter logs or UI. */ }
    connection = undefined;
  };
  const fail = (phase: Phase) => {
    if (ended) return;
    ended = true;
    clearTimeout(timer);
    disconnect();
    onPhase(phase);
  };
  const timer = setTimeout(() => fail('timeout'), timeoutMs);
  const query = () => new URL(session.signedUrl).searchParams;
  onPhase('connecting');
  try {
    sdk.setLogHandler(() => {});
    sdk.authenticate(session.signedUrl, {
      httpExtraSearchParams: query,
      promptCredentials: () => fail('failed'),
      error: () => fail('failed'),
      success: (_authentication, sessions) => {
        if (ended || connecting) return;
        const credentials = sessions?.[0];
        if (!credentials?.sessionId || !credentials.authToken) { fail('failed'); return; }
        connecting = true;
        try {
          void sdk.connect({
            url: session.signedUrl, sessionId: credentials.sessionId, authToken: credentials.authToken,
            divId,
            baseUrl: new URL('/nice-dcv-web-client-sdk/dcvjs-esm', origin).href,
            clipboardAutoSync: false,
            observers: {
              httpExtraSearchParams: query,
              firstFrame: () => {
                if (ended) return;
                clearTimeout(timer);
                onPhase('connected');
              },
              disconnect: () => fail('disconnected'),
              displayLayout: (width, height) => {
                if (!ended && Number.isFinite(width) && Number.isFinite(height)
                  && width > 0 && height > 0 && width <= 8192 && height <= 8192) onLayout(width, height);
              },
            },
          }).then(value => {
            if (ended) { try { value.disconnect(); } catch {} }
            else connection = value;
          }).catch(() => fail('failed'));
        } catch { fail('failed'); }
      },
    });
  } catch { fail('failed'); }
  return () => { ended = true; clearTimeout(timer); disconnect(); };
}
