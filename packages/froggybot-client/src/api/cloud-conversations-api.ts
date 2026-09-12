import type { Attachment, ConversationsApi, MessagePage } from '@froggybot/contracts';
import { apiRoutes } from '@froggybot/contracts';
import { fetchWithTimeout, readableRequestError, UPLOAD_REQUEST_TIMEOUT_MS } from '../http.ts';

import type { ApiRequest } from './cloud-transport';
import { decodeMessagePage } from '../response-contract.ts';

export const createCloudConversationsApi = (request: ApiRequest): ConversationsApi => ({
  messages: (botId, cursor) => request<MessagePage>(apiRoutes.botMessages(botId, cursor), undefined, undefined, decodeMessagePage),
  uploadAttachment: async (asset) => {
    const ticket = await request<{
      file: Attachment;
      upload: { url: string; fields: Record<string, string> };
    }>(apiRoutes.uploads, {
      method: 'POST',
      body: JSON.stringify({ filename: asset.name, size: asset.size }),
    });
    const form = new FormData();
    Object.entries(ticket.upload.fields).forEach(([key, value]) => form.append(key, value));
    if (asset.file) {
      form.append('file', asset.file, asset.name);
    } else {
      form.append('file', {
        uri: asset.uri,
        name: asset.name,
        type: ticket.file.contentType,
      } as unknown as Blob);
    }
    let uploaded: Response;
    try {
      uploaded = await fetchWithTimeout(
        ticket.upload.url,
        { method: 'POST', body: form },
        UPLOAD_REQUEST_TIMEOUT_MS,
      );
    } catch (value) {
      throw readableRequestError(value, 'The file upload could not be completed.');
    }
    if (!uploaded.ok) throw new Error(`The file upload failed (${uploaded.status}).`);
    return request<Attachment>(apiRoutes.upload(ticket.file.id), { method: 'POST' });
  },
  downloadFile: (fileId, groupId) => request<{ url: string }>(
    groupId ? apiRoutes.groupFileDownload(groupId, fileId) : apiRoutes.fileDownload(fileId),
  ).then((value) => value.url),
  sendMessage: async (bot, text, attachmentIds = []) => {
    await request(apiRoutes.botMessages(bot.id), {
      method: 'POST',
      body: JSON.stringify({ text, attachmentIds }),
    });
  },
  cancelMessage: async (botId, turnId) => {
    await request(apiRoutes.botMessageAction(botId, turnId, 'cancel'), { method: 'POST' });
  },
  approveMessage: async (botId, turnId, always = false) => {
    await request(apiRoutes.botMessageAction(botId, turnId, 'approve'), {
      method: 'POST',
      body: JSON.stringify({ always }),
    });
  },
});
