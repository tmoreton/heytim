export type BotBrowserContext = { botId: string; groupId?: string };
export type BotBrowserOpenOptions = { url?: string; display?: 'mobile' | 'desktop' };

export type BotBrowserState = BotBrowserContext & {
  status: 'closed' | 'ready' | 'human_control' | 'expired' | 'opening' | 'resuming';
  contextLabel: string;
  hasSavedLogin: boolean;
  display?: 'mobile' | 'desktop';
  viewport?: { width: number; height: number };
  mobileSiteSupported?: boolean;
  /** A previous operation ended without a confirmed handoff. Explicit cleanup is needed. */
  recoveryRequired?: boolean;
  sessionExpiresAt?: string;
  /** Short-lived capability. Keep only in the open viewer's memory, never chat/storage. */
  liveViewUrl?: string;
  liveViewExpiresAt?: string;
  resumedTurnId?: string;
};

export type Bot = {
  id: string;
  name: string;
  tagline: string;
  color: string;
  prompt: string;
  toolIds: string[];
  extraToolIds?: string[];
  alwaysAllowedToolIds?: string[];
  skillIds: string[];
  templateId?: string;
  templateVersion?: number;
  systemRole?: 'chief';
  createdAt: string;
  updatedAt: string;
  lastMessage: string;
  lastMessageAt: string;
  processing?: boolean;
  processingBotName?: string;
};

export type BotTemplate = {
  id: string;
  version: number;
  name: string;
  tagline: string;
  prompt: string;
  color: string;
  skillIds: string[];
  toolIds: string[];
  category?: string;
  author?: string;
  tags?: string[];
  featured?: boolean;
};

export type Attachment = {
  id: string;
  name: string;
  size: number;
  kind: 'image' | 'document';
  format: string;
  contentType: string;
  createdAt?: string;
};

export type BotDocument = Omit<Attachment, 'createdAt'> & {
  createdAt: string;
};

export type Message = {
  id: string;
  role: 'user' | 'assistant';
  authorType?: 'user' | 'bot';
  authorId?: string;
  authorName?: string;
  authorColor?: string;
  isMine?: boolean;
  source?: 'schedule';
  scheduleName?: string;
  text: string;
  activity?: string[];
  attachments?: Attachment[];
  approvalTools?: string[];
  roundId?: string;
  roundPosition?: number;
  roundSize?: number;
  roundRole?: 'solo' | 'lead' | 'contributor' | 'synthesizer';
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  activityUpdatedAt?: string;
  status:
    | 'complete'
    | 'waiting'
    | 'pending'
    | 'running'
    | 'needs_input'
    | 'awaiting_approval'
    | 'cancelled'
    | 'error';
};

export type ScheduleFrequency = 'hourly' | 'daily' | 'weekdays' | 'weekly' | 'monthly';

export type ScheduledTask = {
  id: string;
  botId: string;
  groupId?: string;
  name: string;
  prompt: string;
  frequency: ScheduleFrequency;
  dayOfWeek?: string;
  dayOfMonth?: number;
  time: string;
  timezone: string;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
  lastRunAt?: string;
  lastStatus?: 'pending' | 'awaiting_approval' | 'complete' | 'cancelled' | 'error';
};

export type ScheduledTaskDraft = Pick<
  ScheduledTask,
  'name' | 'prompt' | 'frequency' | 'dayOfWeek' | 'dayOfMonth' | 'time' | 'timezone' | 'enabled'
>;

export type ScheduleRun = {
  id: string;
  botId: string;
  groupId?: string;
  scheduleId: string;
  scheduleName: string;
  prompt: string;
  status: Message['status'];
  createdAt: string;
  completedAt?: string;
  output?: string;
  activity?: string[];
  approvalTools?: string[];
  attachments?: Attachment[];
};

export type GroupMember = {
  id: string;
  name: string;
  role: 'owner' | 'member';
};

export type GroupBot = {
  id: string;
  ownerId: string;
  name: string;
  tagline: string;
  color: string;
  systemRole?: 'chief';
};

export type GroupDecision = {
  id: string;
  text: string;
  sourceMessageId: string;
  sourceAuthorName: string;
  createdById: string;
  createdByName: string;
  createdAt: string;
};

export type Group = {
  id: string;
  name: string;
  memory: string;
  memoryUpdatedAt?: string;
  memoryUpdatedByName?: string;
  ownerId: string;
  currentUserId: string;
  isOwner: boolean;
  members: GroupMember[];
  bots: GroupBot[];
  decisions: GroupDecision[];
  createdAt: string;
  updatedAt: string;
  lastMessage: string;
  lastMessageAt: string;
  processing?: boolean;
  processingBotName?: string;
};

export type GroupDraft = Pick<Group, 'name' | 'memory'> & { botIds: string[] };

export type InviteKind = 'bot' | 'chat' | 'group' | 'skill';

export type Invitation = {
  kind: InviteKind;
  token: string;
};

export type SharedLink = {
  token: string;
  kind: InviteKind;
  title: string;
  url: string;
  createdAt?: string;
  expiresAt: number;
};

export type MemoryRecord = {
  id: string;
  kind: 'fact' | 'preference' | 'summary';
  content: string;
  createdAt: string;
  scope: 'personal' | 'group';
  source: 'manual' | 'learned' | string;
  botId?: string;
  botName?: string;
};

export type MemorySnapshot = {
  records: MemoryRecord[];
  rawConversationRetentionDays: number;
};

export type InvitePreview = Invitation & {
  title: string;
  description: string;
  inviterName?: string;
  peopleCount?: number;
  bots: Pick<GroupBot, 'name' | 'tagline' | 'color'>[];
  expiresAt: number;
};

export type Capability = {
  id: string;
  name: string;
  description: string;
  provider?: 'stan' | 'frogbot' | 'agentcore' | 'agentcore-gateway' | string;
  risk?: 'read' | 'sandbox' | 'interactive';
  category?: string;
  author?: string;
  tags?: string[];
  featured?: boolean;
  actions?: string[];
  source?: 'official' | 'user';
  editable?: boolean;
  connectedAccount?: string;
};

export type ConnectionAuthType = 'none' | 'bearer' | 'api_key' | 'oauth';

export type ConnectionProvider = {
  id: string;
  name: string;
  description: string;
  category: string;
  authType: 'oauth';
  uiKind: 'oauth';
  iconText: string;
  permissionsSummary: string;
  privacyTitle: string;
  privacyDescription: string;
};

export type Connection = Capability & {
  source: 'user';
  editable: true;
  endpoint: string;
  authType: ConnectionAuthType;
  headerName?: string;
  hasCredential?: boolean;
  connectionStatus: 'connected';
};

export type Skill = Capability & {
  version: number;
  requiredToolIds: string[];
  source: 'official' | 'user';
  visibility: 'private' | 'link' | 'public';
  editable: boolean;
  relationship?: 'owner' | 'installed';
  updatedAt?: string;
};

export type SkillDetail = Skill & {
  instructions: string;
};

export type SkillDraft = Pick<SkillDetail, 'name' | 'description' | 'instructions' | 'requiredToolIds' | 'visibility'>;

export type Bootstrap = {
  bots: Bot[];
  botTemplates: BotTemplate[];
  connectionProviders: ConnectionProvider[];
  needsBotOnboarding: boolean;
  groups: Group[];
  tools: Capability[];
  retiredToolIds: string[];
  skills: Skill[];
};

export type CapabilitySelection = {
  kind: 'skill' | 'tool';
  id: string;
};

export type ConversationSelection = {
  kind: 'bot' | 'group';
  id: string;
};

export type BotDraft = Pick<Bot, 'name' | 'tagline' | 'color' | 'prompt' | 'toolIds' | 'skillIds'> & {
  alwaysAllowedToolIds: string[];
};
