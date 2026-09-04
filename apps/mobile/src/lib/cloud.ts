import 'react-native-get-random-values';

import { Amplify } from 'aws-amplify';

import outputs from '../../amplify_outputs.json';

export const cloudConfigured =
  !outputs.auth.user_pool_id.includes('REPLACE_') && !outputs.custom.apiUrl.includes('REPLACE_');

if (cloudConfigured) {
  Amplify.configure(outputs);
}

export const apiUrl = outputs.custom.apiUrl.replace(/\/$/, '');
export const shareBaseUrl = outputs.custom.shareBaseUrl;
