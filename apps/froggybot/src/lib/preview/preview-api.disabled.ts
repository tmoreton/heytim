import type { FrogBotApi } from '../api';

export const previewEnabled = false;

export const createPreviewApi = (): FrogBotApi => {
  throw new Error('The local preview is not included in this build.');
};
