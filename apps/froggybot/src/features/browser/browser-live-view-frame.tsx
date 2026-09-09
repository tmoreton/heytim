import { useRef, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { WebView } from 'react-native-webview';

import { viewerLocation, VIEWER_CONNECT, VIEWER_READY } from './viewer-location';

export default function BrowserLiveViewFrame({ signedUrl }: { signedUrl: string }) {
  const frame = useRef<WebView>(null);
  const [failed, setFailed] = useState(false);
  const uri = viewerLocation(process.env.EXPO_PUBLIC_BROWSER_VIEWER_ORIGIN || 'https://app.froggybot.com');
  if (failed) return <View style={styles.error}><Text>The in-app browser view could not load. Check your connection, then use Refresh connection.</Text></View>;
  return <WebView
    ref={frame}
    source={{ uri }}
    style={styles.frame}
    accessibilityLabel="Private bot browser — sign in here"
    originWhitelist={[new URL(uri).origin]}
    onShouldStartLoadWithRequest={(request) => request.url === uri}
    onOpenWindow={() => { /* The remote browser handles sites; the viewer itself must never navigate. */ }}
    onMessage={(event) => {
      if (event.nativeEvent.url !== uri || event.nativeEvent.data !== VIEWER_READY) return;
      // In-memory bridge only. Never put a signed capability in source.uri, history or storage.
      const payload = JSON.stringify({ type: VIEWER_CONNECT, signedUrl }).replace(/</g, '\\u003c');
      frame.current?.injectJavaScript(`window.dispatchEvent(new MessageEvent('message', {data: ${payload}, origin: window.location.origin, source: window})); true;`);
    }}
    onError={() => setFailed(true)}
    onHttpError={() => setFailed(true)}
    onContentProcessDidTerminate={() => setFailed(true)}
    onRenderProcessGone={() => setFailed(true)}
    incognito
    cacheEnabled={false}
    sharedCookiesEnabled={false}
    thirdPartyCookiesEnabled={false}
    javaScriptCanOpenWindowsAutomatically={false}
    allowsInlineMediaPlayback
    mediaPlaybackRequiresUserAction={false}
    allowsAirPlayForMediaPlayback={false}
    allowsPictureInPictureMediaPlayback={false}
    webviewDebuggingEnabled={false}
    allowFileAccess={false}
    allowFileAccessFromFileURLs={false}
    allowUniversalAccessFromFileURLs={false}
    mixedContentMode="never"
  />;
}

const styles = StyleSheet.create({ frame: { flex: 1, backgroundColor: '#E9EEEA' }, error: { flex: 1, justifyContent: 'center', padding: 24 } });
