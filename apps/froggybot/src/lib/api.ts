import { createCloudApi } from './cloud-api';
import { createDemoApi } from './demo-api';
import type { AccountApi } from './api/account-api';
import type { BotsApi } from './api/bots-api';
import type { ConversationsApi, MessagePage, UploadAsset } from './api/conversations-api';
import type { GroupsApi } from './api/groups-api';
import type { SchedulesApi } from './api/schedules-api';
import type { BrowserApi } from './browser-api';

export type FrogBotApi = AccountApi & BotsApi & BrowserApi & ConversationsApi & GroupsApi & SchedulesApi;
export type { MessagePage, UploadAsset };

export const createApi = (demo: boolean): FrogBotApi =>
  demo ? createDemoApi() : createCloudApi();
