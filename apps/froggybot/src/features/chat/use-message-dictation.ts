import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { Platform } from 'react-native';
import { ExpoSpeechRecognitionModule, useSpeechRecognitionEvent } from 'expo-speech-recognition';
import { DictationSession } from './dictation-session';

type SetText = (value: string) => void;

export function useMessageDictation(draft: string, setDraft: SetText, setError: SetText, scope = '') {
  const session = useRef(new DictationSession());
  const starting = useRef(false);
  const nativeActive = useRef(false);
  const scopeRef = useRef(scope);
  const [listening, setListening] = useState(false);

  useSpeechRecognitionEvent('start', () => { if (nativeActive.current) setListening(true); });
  useSpeechRecognitionEvent('end', () => {
    nativeActive.current = false;
    session.current.cancel();
    setListening(false);
  });
  useSpeechRecognitionEvent('result', (event) => {
    const text = session.current.result(event.results[0]?.transcript, scopeRef.current);
    if (text !== undefined) setDraft(text);
  });
  useSpeechRecognitionEvent('error', (event) => {
    setListening(false);
    // Errors from an intentionally discarded run must not change the new chat.
    const accepted = session.current.active(scopeRef.current);
    session.current.cancel();
    if (!accepted) return;
    if (event.error === 'aborted' || event.error === 'no-speech') return;
    if (event.error === 'not-allowed') {
      setError('Allow microphone access in Settings to dictate messages.');
      return;
    }
    if (event.error === 'language-not-supported') {
      setError('On-device dictation does not support this iPhone language. Try changing the keyboard language in Settings.');
      return;
    }
    if (event.error === 'service-not-allowed') {
      setError('Turn on Siri & Dictation and download this language in iPhone Settings, then try again.');
      return;
    }
    setError('On-device dictation stopped unexpectedly. Please try again.');
  });

  const abort = useCallback(() => {
    // Synchronous invalidation must happen BEFORE abort emits its final events.
    session.current.cancel();
    if (nativeActive.current) ExpoSpeechRecognitionModule.abort();
    setListening(false);
  }, []);

  useLayoutEffect(() => {
    scopeRef.current = scope;
    const gate = session.current;
    return () => {
      gate.cancel();
      if (nativeActive.current) ExpoSpeechRecognitionModule.abort();
    };
  }, [scope]);

  const toggle = useCallback(async () => {
    if (nativeActive.current) {
      ExpoSpeechRecognitionModule.stop();
      return;
    }
    if (Platform.OS !== 'ios' || starting.current) return;
    starting.current = true;
    const token = session.current.begin(draft, scope);
    try {
      const permissions = await ExpoSpeechRecognitionModule.requestMicrophonePermissionsAsync();
      if (!session.current.current(token, scopeRef.current)) return;
      if (!permissions.granted) {
        setError('Allow microphone access in Settings to dictate messages.');
        return;
      }
      const deviceLocale = (Intl.DateTimeFormat().resolvedOptions().locale || 'en-US').replaceAll('_', '-');
      const { locales } = await ExpoSpeechRecognitionModule.getSupportedLocales({});
      const language = deviceLocale.split('-')[0];
      const locale = locales.find((value) => value.toLowerCase() === deviceLocale.toLowerCase())
        ?? locales.find((value) => value.toLowerCase().startsWith(`${language.toLowerCase()}-`))
        ?? 'en-US';
      if (!session.current.start(token, scopeRef.current)) return;
      setError('');
      nativeActive.current = true;
      ExpoSpeechRecognitionModule.start({
        lang: locale,
        interimResults: true,
        continuous: false,
        requiresOnDeviceRecognition: true,
        addsPunctuation: true,
        iosTaskHint: 'dictation',
        recordingOptions: { persist: false },
      });
    } catch {
      if (!session.current.current(token, scopeRef.current)) return;
      session.current.cancel();
      nativeActive.current = false;
      setListening(false);
      setError('On-device dictation could not start. Please check the app permissions in Settings.');
    } finally {
      starting.current = false;
    }
  }, [draft, scope, setError]);

  return { listening, abort, toggle };
}
