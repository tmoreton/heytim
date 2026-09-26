#!/usr/bin/env node

const apiUrl = process.env.HEYTIM_API_URL;
const idToken = process.env.HEYTIM_ID_TOKEN;
if (!apiUrl || !idToken) {
  throw new Error('Set HEYTIM_API_URL and HEYTIM_ID_TOKEN before running the workflow test.');
}
const deleteAccount = process.env.HEYTIM_DISPOSABLE_ACCOUNT === '1'
  || process.env.HEYTIM_DELETE_ACCOUNT === '1';

const terminalStatuses = new Set(['complete', 'cancelled', 'error']);
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
    throw new Error(`${method} ${path} failed (${response.status}): ${value.message ?? 'unknown error'}`);
  }
  return value;
};

const waitForTurn = async (botId, turnId, timeoutMs = 240_000) => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const { messages } = await request('GET', `/bots/${encodeURIComponent(botId)}/messages`);
    const reply = messages.find((message) => message.id === `${turnId}-assistant`);
    if (reply && terminalStatuses.has(reply.status)) return reply;
    await new Promise((resolve) => setTimeout(resolve, 1_500));
  }
  throw new Error(`Turn ${turnId} did not finish within ${timeoutMs}ms.`);
};

const requireValue = (condition, message) => {
  if (!condition) throw new Error(message);
};

let accountDeletionQueued = false;
let cleanupSucceeded = true;
let workflowError;
const createdBotIds = [];
const completed = [];

const deleteBot = async (botId) => {
  await request('DELETE', `/bots/${encodeURIComponent(botId)}`);
  const index = createdBotIds.indexOf(botId);
  if (index >= 0) createdBotIds.splice(index, 1);
};

try {
  const bootstrap = await request('GET', '/bootstrap');
  requireValue(Array.isArray(bootstrap.bots) && bootstrap.bots.length >= 3, 'Bootstrap did not return the default bots.');
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
  const attachmentTurn = await request('POST', `/bots/${encodeURIComponent(standardBot.id)}/messages`, {
    text: 'Read the attached file and reply with a short confirmation.',
    attachmentIds: [attachment.id],
  });
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
  const scheduledTurn = await request(
    'POST',
    `/bots/${encodeURIComponent(standardBot.id)}/schedules/${encodeURIComponent(schedule.id)}/run`,
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
    prompt: 'Reply concisely. Use the browser only when explicitly requested.',
    toolIds: ['browser'],
    skillIds: [],
  });
  createdBotIds.push(approvalBot.id);
  const deniedTurn = await request('POST', `/bots/${encodeURIComponent(approvalBot.id)}/messages`, {
    text: 'Open example.com and report the page title.',
  });
  requireValue(deniedTurn.status === 'awaiting_approval', 'The interactive turn did not wait for approval.');
  await request(
    'POST',
    `/bots/${encodeURIComponent(approvalBot.id)}/messages/${encodeURIComponent(deniedTurn.turnId)}/cancel`,
  );
  const deniedReply = await waitForTurn(approvalBot.id, deniedTurn.turnId);
  requireValue(deniedReply.status === 'cancelled', 'The denied interactive turn was not cancelled.');

  const approvedTurn = await request('POST', `/bots/${encodeURIComponent(approvalBot.id)}/messages`, {
    text: 'Reply only with: one-time approval passed. Do not use a tool.',
  });
  requireValue(approvedTurn.status === 'awaiting_approval', 'The second interactive turn did not wait for approval.');
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
