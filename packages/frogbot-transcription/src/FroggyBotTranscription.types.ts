import type { NativeModule } from 'expo';

export type FroggyBotTranscriptionResult = {
  transcript: string;
  isFinal: boolean;
};

export type FroggyBotTranscriptionError = {
  code: 'aborted' | 'audio-capture' | 'model-unavailable' | 'not-allowed' | 'processing';
  message: string;
};

export type FroggyBotTranscriptionEvents = {
  start: () => void;
  result: (event: FroggyBotTranscriptionResult) => void;
  error: (event: FroggyBotTranscriptionError) => void;
  end: () => void;
};

export declare class FroggyBotTranscriptionModuleType extends NativeModule<FroggyBotTranscriptionEvents> {
  readonly isAvailable: boolean;
  readonly modelName: string;
  requestMicrophonePermission(): Promise<boolean>;
  start(): void;
  stop(): void;
  abort(): void;
}
