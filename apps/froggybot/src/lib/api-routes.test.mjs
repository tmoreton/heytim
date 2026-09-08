import assert from 'node:assert/strict';
import test from 'node:test';

import { apiRoutes } from './api-routes.ts';

test('encodes every dynamic API path segment', () => {
  assert.equal(apiRoutes.botMessages('bot/a b'), '/bots/bot%2Fa%20b/messages');
  assert.equal(apiRoutes.groupMember('group/one', 'member two'), '/groups/group%2Fone/members/member%20two');
  assert.equal(apiRoutes.botScheduleRun('bot/one', 'schedule?two'), '/bots/bot%2Fone/schedules/schedule%3Ftwo/run');
});
