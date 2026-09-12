import type { Attachment, BotDocument } from '@froggybot/contracts';

import { demoState } from './demo-state';

export const demoUploadAttachment = async (asset: {
  name: string;
  size: number;
  mimeType?: string;
}): Promise<Attachment> => {
  const attachment: Attachment = {
    id: `demo-file-${Date.now()}-${demoState.uploadedAttachments.size}`,
    name: asset.name,
    size: asset.size,
    kind: asset.mimeType?.startsWith('image/') ? 'image' : 'document',
    format: asset.name.split('.').pop()?.toLowerCase() ?? 'txt',
    contentType: asset.mimeType ?? 'application/octet-stream',
    createdAt: new Date().toISOString(),
  };
  demoState.uploadedAttachments.set(attachment.id, attachment);
  return { ...attachment };
};

export const demoBotDocuments = async (botId: string): Promise<BotDocument[]> =>
  (demoState.botDocuments.get(botId) ?? []).map((document) => ({ ...document }));
