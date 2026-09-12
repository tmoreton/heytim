import type {
  AccountApi,
  BotsApi,
  ConversationsApi,
  GroupsApi,
  SchedulesApi,
} from '@froggybot/contracts';

import { createCloudAccountApi } from './api/cloud-account-api.ts';
import { createCloudBotsApi } from './api/cloud-bots-api.ts';
import { createCloudConversationsApi } from './api/cloud-conversations-api.ts';
import { createCloudGroupsApi } from './api/cloud-groups-api.ts';
import { createCloudSchedulesApi } from './api/cloud-schedules-api.ts';
import { createCloudTransport } from './api/cloud-transport.ts';
import { createBrowserApi, type BrowserApi } from './browser-api.ts';

export type FrogBotApi = AccountApi & BotsApi & BrowserApi & ConversationsApi & GroupsApi & SchedulesApi;

export type FrogBotClientOptions = {
  apiUrl: string;
  getIdToken: () => Promise<string | undefined>;
};

export const createFrogBotClient = (options: FrogBotClientOptions): FrogBotApi => {
  const { request, publicRequest } = createCloudTransport(options);
  return {
    ...createCloudAccountApi(request, publicRequest),
    ...createCloudBotsApi(request),
    ...createBrowserApi(request),
    ...createCloudConversationsApi(request),
    ...createCloudGroupsApi(request),
    ...createCloudSchedulesApi(request),
  };
};

export type { BrowserApi } from './browser-api.ts';
export { BOT_COLORS, CHIEF_COLOR, CHIEF_TEMPLATE_ID, chiefFirst, displayBotColor } from './bot-branding.ts';
export { ApiClientError, apiErrorCode } from './http.ts';
export { browserViewports, viewerViewport } from './browser-display.ts';
export {
  browserError,
  hasBrowserCapability,
  isLiveViewUrl,
  liveViewDeadline,
  shouldUseBotBrowserForChatLinks,
  withoutLiveView,
} from './browser-policy.ts';
export { VIEWER_CONNECT, VIEWER_PATH, VIEWER_READY, viewerLocation } from './viewer-location.ts';
export {
  chooseAvailableSelection,
  composerPrimaryAction,
  isActiveResponse,
  isPendingMessage,
  isRefreshingMessage,
  mergeEarlierMessages,
  mergeLatestMessages,
  reconcileBootstrap,
  reconcileMessages,
} from './state/chat-state.ts';
export { nextPollingDelay } from './state/polling.ts';
export { createBotDraft } from './bot-draft.ts';
export { requiredToolLabels } from './capability-labels.ts';
export { capabilityAccessLabel, catalogTools, isUserConnection, userConnections } from './connection-access.ts';
export { isPreviewableImage, readableFileSize } from './file-preview.ts';
export { firstRouteParam, invitationFromParams, invitationFromUrl, invitationUrl } from './invitation-url.ts';
export { messagePreview } from './message-preview.ts';
export { formatElapsed, messageTimingLabel } from './message-timing.ts';
export { resumeBrowserWithProfilePolling } from './resume-browser.ts';
export { describeSchedule, deviceTimezone, formatTime, latestRunLabel, parseTimeInput, WEEKDAYS } from './schedules.ts';
