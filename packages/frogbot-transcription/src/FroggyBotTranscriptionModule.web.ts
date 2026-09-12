import { NativeModule, registerWebModule } from 'expo';

import type {
  FroggyBotTranscriptionEvents,
  FroggyBotTranscriptionModuleType,
} from './FroggyBotTranscription.types';

class FroggyBotTranscriptionWeb
  extends NativeModule<FroggyBotTranscriptionEvents>
  implements FroggyBotTranscriptionModuleType {
  readonly isAvailable = false;
  readonly modelName = 'nemotron-3.5-asr-streaming-0.6b-1120ms';

  async requestMicrophonePermission() {
    return false;
  }

  start() {}
  stop() {}
  abort() {}
}

export default registerWebModule(FroggyBotTranscriptionWeb, 'FroggyBotTranscription');
