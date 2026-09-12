import type { Attachment, Bot, Message } from '../types';

export type UploadAsset = {
  uri: string;
  name: string;
  size: number;
  mimeType?: string;
  file?: File;
};

export type MessagePage = {
  messages: Message[];
  nextToken?: string;
};

export interface ConversationsApi {
  messages(botId: string, cursor?: string): Promise<MessagePage>;
  uploadAttachment(asset: UploadAsset): Promise<Attachment>;
  downloadFile(fileId: string, groupId?: string): Promise<string>;
  sendMessage(bot: Bot, text: string, attachmentIds?: string[]): Promise<void>;
  cancelMessage(botId: string, turnId: string): Promise<void>;
  approveMessage(botId: string, turnId: string, always?: boolean): Promise<void>;
}
