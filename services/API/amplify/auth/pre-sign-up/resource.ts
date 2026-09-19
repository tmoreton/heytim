import { defineFunction } from '@aws-amplify/backend';

export const preSignUp = defineFunction({
  name: 'heytim-invite-check',
  resourceGroupName: 'auth',
  timeoutSeconds: 5,
  memoryMB: 256,
});
