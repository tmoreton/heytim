import type {
  AppConstraints,
  Bootstrap,
  Bot,
  ConnectionProvider,
  Group,
  GroupDecision,
  Message,
  MessagePage,
} from '@froggybot/contracts';

const BOT_ACTIONS = new Set(['edit', 'documents', 'browser', 'schedule', 'share', 'clear', 'delete']);
const GROUP_ACTIONS = new Set(['view', 'edit', 'share', 'schedule', 'delete', 'viewMemory', 'manageMemory']);
const MEMBER_ACTIONS = new Set(['remove', 'leave']);
const DECISION_ACTIONS = new Set(['remove']);
const MESSAGE_ACTIONS = new Set(['reject', 'approveOnce', 'approveAlways', 'cancel', 'saveDecision']);
const CONSTRAINT_FIELDS: (keyof AppConstraints)[] = [
  'botNameMaxLength',
  'botTaglineMaxLength',
  'botPromptMaxLength',
  'groupNameMaxLength',
  'groupMemoryMaxLength',
  'messageMaxLength',
  'scheduleNameMaxLength',
  'schedulePromptMaxLength',
  'scheduleDayOfMonthMin',
  'scheduleDayOfMonthMax',
  'skillNameMaxLength',
  'skillDescriptionMaxLength',
  'skillInstructionsMaxLength',
  'memoryMaxLength',
  'maxAttachmentsPerMessage',
  'imageMaxBytes',
  'documentMaxBytes',
  'maxPhotoDimension',
];
const CONNECTION_PROVIDER_FIELDS: (keyof ConnectionProvider)[] = [
  'id',
  'name',
  'description',
  'category',
  'iconText',
  'permissionsSummary',
  'privacyTitle',
  'privacyDescription',
  'connectLabel',
  'reconnectLabel',
];

const invalid = (): never => {
  throw new Error('FroggyBot returned data the app cannot safely use. Please try again.');
};

const record = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid();
  return value as Record<string, unknown>;
};

const stringField = (value: Record<string, unknown>, key: string) => {
  if (typeof value[key] !== 'string') invalid();
};

const objectArray = (value: Record<string, unknown>, key: string): Record<string, unknown>[] => {
  const entries = value[key];
  if (!Array.isArray(entries)) return invalid();
  return entries.map(record);
};

const actions = (value: Record<string, unknown>, allowed: Set<string>) => {
  if (value.allowedActions === undefined) return;
  if (
    !Array.isArray(value.allowedActions)
    || value.allowedActions.some((action) => typeof action !== 'string' || !allowed.has(action))
  ) invalid();
};

export const decodeBot = (value: unknown): Bot => {
  const bot = record(value);
  stringField(bot, 'id');
  stringField(bot, 'name');
  actions(bot, BOT_ACTIONS);
  return bot as Bot;
};

export const decodeGroup = (value: unknown): Group => {
  const group = record(value);
  stringField(group, 'id');
  stringField(group, 'name');
  actions(group, GROUP_ACTIONS);
  objectArray(group, 'members').forEach((member) => actions(member, MEMBER_ACTIONS));
  objectArray(group, 'bots').forEach((bot) => {
    stringField(bot, 'id');
    stringField(bot, 'name');
  });
  objectArray(group, 'decisions').forEach((decision) => actions(decision, DECISION_ACTIONS));
  return group as Group;
};

export const decodeGroupDecision = (value: unknown): GroupDecision => {
  const decision = record(value);
  stringField(decision, 'id');
  stringField(decision, 'text');
  actions(decision, DECISION_ACTIONS);
  return decision as GroupDecision;
};

const decodeMessage = (value: unknown): Message => {
  const message = record(value);
  stringField(message, 'id');
  stringField(message, 'text');
  stringField(message, 'status');
  actions(message, MESSAGE_ACTIONS);
  return message as Message;
};

const decodeConnectionProvider = (value: unknown): ConnectionProvider => {
  const provider = record(value);
  for (const field of CONNECTION_PROVIDER_FIELDS) stringField(provider, field);
  return provider as ConnectionProvider;
};

export const decodeMessagePage = (value: unknown): MessagePage => {
  const page = record(value);
  const messages = page.messages;
  if (!Array.isArray(messages)) return invalid();
  if (page.nextToken !== undefined && typeof page.nextToken !== 'string') invalid();
  return { ...page, messages: messages.map(decodeMessage) } as MessagePage;
};

export const decodeBootstrap = (value: unknown): Bootstrap => {
  const bootstrap = record(value);
  const constraints = record(bootstrap.constraints);
  for (const field of CONSTRAINT_FIELDS) {
    const constraint = constraints[field];
    if (typeof constraint !== 'number' || !Number.isFinite(constraint) || constraint <= 0) invalid();
  }
  const safeConstraints = constraints as unknown as AppConstraints;
  if (
    safeConstraints.scheduleDayOfMonthMin > safeConstraints.scheduleDayOfMonthMax
    || typeof bootstrap.needsBotOnboarding !== 'boolean'
  ) invalid();
  const bots = objectArray(bootstrap, 'bots').map(decodeBot);
  const groups = objectArray(bootstrap, 'groups').map(decodeGroup);
  for (const key of ['botTemplates', 'tools', 'retiredToolIds', 'skills']) {
    if (!Array.isArray(bootstrap[key])) invalid();
  }
  const connectionProviders = objectArray(bootstrap, 'connectionProviders').map(
    decodeConnectionProvider,
  );
  return {
    ...bootstrap,
    bots,
    connectionProviders,
    groups,
    constraints: safeConstraints,
  } as Bootstrap;
};
