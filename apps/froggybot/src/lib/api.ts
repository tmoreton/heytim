import { fetchAuthSession } from 'aws-amplify/auth';

import { createFrogBotClient, type FrogBotApi } from '@froggybot/client';
import type { MessagePage, UploadAsset } from '@froggybot/contracts';
import { createPreviewApi } from '@froggybot/preview-api';
import { apiUrl } from './cloud';

export type { FrogBotApi };
export type { MessagePage, UploadAsset };

const createCloudApi = (): FrogBotApi => createFrogBotClient({
  apiUrl,
  getIdToken: async () => (await fetchAuthSession()).tokens?.idToken?.toString(),
});

export const createApi = (demo: boolean): FrogBotApi =>
  demo ? createPreviewApi() : createCloudApi();
