import { requireNativeModule } from 'expo';

import type { FroggyBotTranscriptionModuleType } from './FroggyBotTranscription.types';

export default requireNativeModule<FroggyBotTranscriptionModuleType>('FroggyBotTranscription');
