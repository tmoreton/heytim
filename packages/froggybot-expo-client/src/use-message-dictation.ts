import { useEventListener } from 'expo';
import { useCallback, useLayoutEffect, useRef, useState } from 'react';

import { DictationSession, FroggyBotTranscription } from '@froggybot/transcription';

type SetText = (value: string) => void;

export function useMessageDictation(draft: string, setDraft: SetText, setError: SetText, scope = '') {
  const session = useRef(new DictationSession());
  const starting = useRef(false);
  const nativeActive = useRef(false);
  const scopeRef = useRef(scope);
  const [listening, setListening] = useState(false);

  useEventListener(FroggyBotTranscription, 'start', () => {
    if (nativeActive.current) setListening(true);
  });
  useEventListener(FroggyBotTranscription, 'end', () => {
    nativeActive.current = false;
    session.current.cancel();
    setListening(false);
  });
  useEventListener(FroggyBotTranscription, 'result', (event) => {
    const text = session.current.result(event.transcript, scopeRef.current);
    if (text !== undefined) setDraft(text);
  });
  useEventListener(FroggyBotTranscription, 'error', (event) => {
    setListening(false);
    // Errors from an intentionally discarded run must not change the new chat.
    const accepted = session.current.active(scopeRef.current);
    session.current.cancel();
    if (!accepted) return;
    if (event.code === 'aborted') return;
    if (event.code === 'not-allowed') {
      setError('Allow microphone access in Settings to dictate messages.');
      return;
    }
    if (event.code === 'model-unavailable') {
      setError('The on-device transcription model is unavailable. Reinstall or update FroggyBot, then try again.');
      return;
    }
    setError('On-device dictation stopped unexpectedly. Please try again.');
  });

  const abort = useCallback(() => {
    // Synchronous invalidation must happen BEFORE abort emits its final events.
    session.current.cancel();
    if (nativeActive.current) FroggyBotTranscription.abort();
    setListening(false);
  }, []);

  useLayoutEffect(() => {
    scopeRef.current = scope;
    const gate = session.current;
    return () => {
      gate.cancel();
      if (nativeActive.current) FroggyBotTranscription.abort();
    };
  }, [scope]);

  const toggle = useCallback(async () => {
    if (nativeActive.current) {
      FroggyBotTranscription.stop();
      return;
    }
    if (!FroggyBotTranscription.isAvailable || starting.current) return;
    starting.current = true;
    const token = session.current.begin(draft, scope);
    try {
      const granted = await FroggyBotTranscription.requestMicrophonePermission();
      if (!session.current.current(token, scopeRef.current)) return;
      if (!granted) {
        setError('Allow microphone access in Settings to dictate messages.');
        return;
      }
      if (!session.current.start(token, scopeRef.current)) return;
      setError('');
      nativeActive.current = true;
      FroggyBotTranscription.start();
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

  return {
    listening,
    available: FroggyBotTranscription.isAvailable,
    abort,
    toggle,
  };
}
