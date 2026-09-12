import type { FrogBotApi } from './api';
import { createCloudAccountApi } from './api/cloud-account-api';
import { createCloudBotsApi } from './api/cloud-bots-api';
import { createCloudConversationsApi } from './api/cloud-conversations-api';
import { createCloudGroupsApi } from './api/cloud-groups-api';
import { createCloudSchedulesApi } from './api/cloud-schedules-api';
import { createCloudTransport } from './api/cloud-transport';
import { createBrowserApi } from './browser-api';

export const createCloudApi = (): FrogBotApi => {
  const { request, publicRequest } = createCloudTransport();
  return {
    ...createCloudAccountApi(request, publicRequest),
    ...createCloudBotsApi(request),
    ...createBrowserApi(request),
    ...createCloudConversationsApi(request),
    ...createCloudGroupsApi(request),
    ...createCloudSchedulesApi(request),
  };
};
