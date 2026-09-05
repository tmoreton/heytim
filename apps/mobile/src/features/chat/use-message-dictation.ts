import { useCallback, useRef, useState } from 'react';
import { Platform } from 'react-native';
import { ExpoSpeechRecognitionModule, useSpeechRecognitionEvent } from 'expo-speech-recognition';

type SetText = (value: string) => void;

export function useMessageDictation(draft: string, setDraft: SetText, setError: SetText) {
  const baseText = useRef('');
  const [listening, setListening] = useState(false);

  useSpeechRecognitionEvent('start', () => setListening(true));
  useSpeechRecognitionEvent('end', () => setListening(false));
  useSpeechRecognitionEvent('result', (event) => {
    const transcript = event.results[0]?.transcript?.trim();
    if (!transcript) return;
    setDraft(baseText.current ? `${baseText.current} ${transcript}` : transcript);
  });
  useSpeechRecognitionEvent('error', (event) => {
    setListening(false);
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
    if (listening) ExpoSpeechRecognitionModule.abort();
  }, [listening]);

  const stop = useCallback(() => {
    if (listening) ExpoSpeechRecognitionModule.stop();
  }, [listening]);

  const toggle = useCallback(async () => {
    if (listening) {
      ExpoSpeechRecognitionModule.stop();
      return;
    }
    if (Platform.OS !== 'ios') return;
    try {
      const permissions = await ExpoSpeechRecognitionModule.requestMicrophonePermissionsAsync();
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
      baseText.current = draft.trimEnd();
      setError('');
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
      setListening(false);
      setError('On-device dictation could not start. Please check the app permissions in Settings.');
    }
  }, [draft, listening, setError]);

  return { listening, abort, stop, toggle };
}
