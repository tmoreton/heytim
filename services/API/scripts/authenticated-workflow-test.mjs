#!/usr/bin/env node

import { assertBootstrapReady } from './bootstrap-release-contract.mjs';

const apiUrl = process.env.HEYTIM_API_URL;
const idToken = process.env.HEYTIM_ID_TOKEN;
if (!apiUrl || !idToken) {
  throw new Error('Set HEYTIM_API_URL and HEYTIM_ID_TOKEN before running the workflow test.');
}
const deleteAccount = process.env.HEYTIM_DISPOSABLE_ACCOUNT === '1'
  || process.env.HEYTIM_DELETE_ACCOUNT === '1';

const terminalStatuses = new Set(['complete', 'cancelled', 'error']);
const activeStatuses = new Set([
  'pending', 'running', 'waiting', 'needs_input', 'awaiting_approval', 'awaiting_device',
]);
const baseUrl = apiUrl.endsWith('/') ? apiUrl.slice(0, -1) : apiUrl;

const request = async (method, path, body) => {
  const response = await fetch(`${baseUrl}${path}`, {
    method,
    headers: {
      authorization: `Bearer ${idToken}`,
      ...(body === undefined ? {} : { 'content-type': 'application/json' }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(25_000),
  });
  const text = await response.text();
  const value = text ? JSON.parse(text) : {};
  if (!response.ok) {
    const message = typeof value.message === 'string' ? value.message : 'unknown error';
    const error = new Error(`${method} ${path} failed (${response.status}): ${message}`);
    error.status = response.status;
    error.apiMessage = message;
    throw error;
  }
  return value;
};

const waitForTurnStatus = async (botId, turnId, statuses, timeoutMs = 240_000) => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const { messages } = await request('GET', `/bots/${encodeURIComponent(botId)}/messages`);
    const reply = messages.find((message) => message.id === `${turnId}-assistant`);
    if (reply && statuses.has(reply.status)) return reply;
    if (reply && terminalStatuses.has(reply.status)) {
      throw new Error(`Turn ${turnId} ended as ${reply.status} before the expected state.`);
    }
    if (reply && ['awaiting_approval', 'awaiting_device', 'needs_input'].includes(reply.status)) {
      throw new Error(`Turn ${turnId} paused as ${reply.status} before the expected state.`);
    }
    await new Promise((resolve) => setTimeout(resolve, 1_500));
  }
  throw new Error(`Turn ${turnId} did not reach the expected state within ${timeoutMs}ms.`);
};
const waitForTurn = (botId, turnId) => waitForTurnStatus(botId, turnId, terminalStatuses);
const waitForApproval = (botId, turnId) => waitForTurnStatus(
  botId, turnId, new Set(['awaiting_approval']),
);

const requireValue = (condition, message) => {
  if (!condition) throw new Error(message);
};

let accountDeletionQueued = false;
let cleanupSucceeded = true;
let workflowError;
const createdBotIds = [];
const startedTurnIds = new Map();
const completed = [];

const rememberTurn = (botId, turn) => {
  requireValue(typeof turn.turnId === 'string' && turn.turnId, 'The queued turn has no ID.');
  if (!startedTurnIds.has(botId)) startedTurnIds.set(botId, new Set());
  startedTurnIds.get(botId).add(turn.turnId);
  return turn;
};

const deleteBot = async (botId) => {
  const { messages } = await request('GET', `/bots/${encodeURIComponent(botId)}/messages`);
  let cancelledInFlight = false;
  for (const turnId of startedTurnIds.get(botId) ?? []) {
    const reply = messages.find((message) => message.id === `${turnId}-assistant`);
    if (reply && !activeStatuses.has(reply.status)) continue;
    try {
      await request('POST', `/bots/${encodeURIComponent(botId)}/messages/${encodeURIComponent(turnId)}/cancel`);
      cancelledInFlight = true;
    } catch (error) {
      const current = await request('GET', `/bots/${encodeURIComponent(botId)}/messages`);
      const settled = current.messages.find((message) => message.id === `${turnId}-assistant`);
      if (!settled || !terminalStatuses.has(settled.status)) throw error;
    }
  }
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      await request('DELETE', `/bots/${encodeURIComponent(botId)}`);
      break;
    } catch (error) {
      if (!cancelledInFlight || error.status !== 409
          || error.apiMessage !== 'Wait for this HeyTim to finish before deleting it'
          || attempt === 3) throw error;
      await new Promise((resolve) => setTimeout(resolve, 1_000 * (attempt + 1)));
    }
  }
  const index = createdBotIds.indexOf(botId);
  if (index >= 0) createdBotIds.splice(index, 1);
  startedTurnIds.delete(botId);
};

try {
  const bootstrap = await request('GET', '/bootstrap');
  assertBootstrapReady(bootstrap);
  completed.push('bootstrap');

  const botSuffix = new Date().toISOString().replaceAll(/[^0-9]/g, '').slice(0, 14);
  const standardBot = await request('POST', '/bots', {
    name: `Workflow Check ${botSuffix}`,
    tagline: 'Temporary authenticated workflow verification bot.',
    color: '#3984F6',
    prompt: 'Follow the request and answer concisely.',
    toolIds: [],
    skillIds: [],
  });
  createdBotIds.push(standardBot.id);

  const attachmentText = 'HeyTim authenticated attachment workflow passed.';
  const attachmentBytes = new TextEncoder().encode(attachmentText);
  const ticket = await request('POST', '/uploads', {
    filename: `workflow-${botSuffix}.txt`,
    size: attachmentBytes.byteLength,
  });
  const form = new FormData();
  for (const [key, value] of Object.entries(ticket.upload.fields)) form.append(key, value);
  form.append('file', new Blob([attachmentBytes], { type: ticket.file.contentType }), ticket.file.name);
  const upload = await fetch(ticket.upload.url, {
    method: 'POST',
    body: form,
    signal: AbortSignal.timeout(25_000),
  });
  requireValue(upload.ok, `The S3 upload failed (${upload.status}).`);
  const attachment = await request('POST', `/uploads/${encodeURIComponent(ticket.file.id)}/complete`);
  requireValue(attachment.id === ticket.file.id, 'The completed attachment ID did not match the upload ticket.');
  const attachmentTurn = rememberTurn(
    standardBot.id,
    await request('POST', `/bots/${encodeURIComponent(standardBot.id)}/messages`, {
      text: 'Read the attached file and reply with a short confirmation.',
      attachmentIds: [attachment.id],
    }),
  );
  const attachmentReply = await waitForTurn(standardBot.id, attachmentTurn.turnId);
  requireValue(attachmentReply.status === 'complete', `Attachment turn ended as ${attachmentReply.status}.`);
  completed.push('attachment upload and agent read');

  const schedule = await request('POST', `/bots/${encodeURIComponent(standardBot.id)}/schedules`, {
    name: 'Disposable workflow check',
    prompt: 'Reply with: scheduled workflow passed',
    frequency: 'daily',
    time: '09:00',
    timezone: 'UTC',
    enabled: false,
  });
  const scheduledTurn = rememberTurn(
    standardBot.id,
    await request(
      'POST',
      `/bots/${encodeURIComponent(standardBot.id)}/schedules/${encodeURIComponent(schedule.id)}/run`,
    ),
  );
  const scheduledReply = await waitForTurn(standardBot.id, scheduledTurn.turnId);
  requireValue(scheduledReply.status === 'complete', `Scheduled turn ended as ${scheduledReply.status}.`);
  await request(
    'DELETE',
    `/bots/${encodeURIComponent(standardBot.id)}/schedules/${encodeURIComponent(schedule.id)}`,
  );
  completed.push('schedule create, run, and delete');

  const share = await request('POST', '/shares', { botId: standardBot.id, scope: 'bot' });
  const shareToken = new URL(share.url).searchParams.get('token');
  requireValue(shareToken, 'The share URL did not include a token.');
  await request('DELETE', `/shares/${encodeURIComponent(shareToken)}`);
  const shares = await request('GET', '/shares');
  requireValue(!shares.shares.some((item) => item.token === shareToken), 'The revoked share remained active.');
  completed.push('share creation and revocation');

  const approvalBot = await request('POST', '/bots', {
    name: `Approval Check ${botSuffix}`,
    tagline: 'Temporary approval workflow verification bot.',
    color: '#F46A27',
    prompt: 'Reply concisely. Use the browser when explicitly requested.',
    toolIds: ['browser'],
    skillIds: [],
    actionApprovalMode: 'ask',
  });
  createdBotIds.push(approvalBot.id);
  requireValue(
    approvalBot.actionApprovalMode === 'ask'
      && !approvalBot.alwaysAllowedToolIds?.includes('browser'),
    'The approval bot was not created in ask mode.',
  );
  const deniedTurn = rememberTurn(
    approvalBot.id,
    await request('POST', `/bots/${encodeURIComponent(approvalBot.id)}/messages`, {
      text: 'Use the browser to open example.com. Do not answer without using the browser.',
    }),
  );
  requireValue(deniedTurn.status === 'pending', 'The interactive turn was not queued.');
  const deniedProposal = await waitForApproval(approvalBot.id, deniedTurn.turnId);
  requireValue(
    deniedProposal.allowedActions?.includes('approveOnce')
      && deniedProposal.approvalTools?.includes('Interactive browser'),
    'The browser action did not request one-time approval.',
  );
  await request(
    'POST',
    `/bots/${encodeURIComponent(approvalBot.id)}/messages/${encodeURIComponent(deniedTurn.turnId)}/cancel`,
  );
  const deniedReply = await waitForTurn(approvalBot.id, deniedTurn.turnId);
  requireValue(deniedReply.status === 'cancelled', 'The denied interactive turn was not cancelled.');

  const approvedTurn = rememberTurn(
    approvalBot.id,
    await request('POST', `/bots/${encodeURIComponent(approvalBot.id)}/messages`, {
      text: 'Use the browser once to open example.com. After that one action, reply only with: one-time approval passed.',
    }),
  );
  requireValue(approvedTurn.status === 'pending', 'The second interactive turn was not queued.');
  const approvedProposal = await waitForApproval(approvalBot.id, approvedTurn.turnId);
  requireValue(
    approvedProposal.allowedActions?.includes('approveOnce')
      && approvedProposal.approvalTools?.includes('Interactive browser'),
    'The second browser action did not request one-time approval.',
  );
  await request(
    'POST',
    `/bots/${encodeURIComponent(approvalBot.id)}/messages/${encodeURIComponent(approvedTurn.turnId)}/approve`,
  );
  const approvedReply = await waitForTurn(approvalBot.id, approvedTurn.turnId);
  requireValue(approvedReply.status === 'complete', `Approved turn ended as ${approvedReply.status}.`);
  completed.push('approval deny, allow-once, and cancellation');

  await deleteBot(approvalBot.id);
  await deleteBot(standardBot.id);
  completed.push('temporary bot cleanup');
} catch (error) {
  workflowError = error;
} finally {
  for (const botId of [...createdBotIds].reverse()) {
    try {
      await deleteBot(botId);
    } catch (error) {
      cleanupSucceeded = false;
      console.error(`Could not delete temporary bot ${botId}:`, error instanceof Error ? error.message : error);
    }
  }
  if (deleteAccount) {
    try {
      const deletion = await request('DELETE', '/account');
      accountDeletionQueued = deletion.deletionStarted === true;
    } catch (error) {
      console.error(error instanceof Error ? error.message : error);
    }
  }
}

if (workflowError) throw workflowError;
requireValue(cleanupSucceeded, 'One or more temporary workflow-test bots could not be deleted.');
if (deleteAccount) {
  requireValue(accountDeletionQueued, 'Disposable account deletion was not queued.');
  completed.push('account deletion queued');
}
console.log(JSON.stringify({ passed: true, completed }, null, 2));
