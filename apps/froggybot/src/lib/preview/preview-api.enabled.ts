import { Asset } from 'expo-asset';
import { createDemoApi } from '@froggybot/preview';

const demoImageUrl = Asset.fromModule(
  require('../../../assets/images/frogbot-foreground.png'),
).uri;

export const previewEnabled = true;
export const createPreviewApi = () => createDemoApi(demoImageUrl);
