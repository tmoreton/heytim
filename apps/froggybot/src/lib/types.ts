export type Bot = {
  id: string;
  name: string;
  tagline: string;
  color: string;
  prompt: string;
  toolIds: string[];
  extraToolIds?: string[];
  skillIds: string[];
  systemRole?: 'chief';
  createdAt: string;
  updatedAt: string;
  lastMessage: string;
  lastMessageAt: string;
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

export type ScheduleFrequency = 'daily' | 'weekdays' | 'weekly' | 'monthly';

export type ScheduledTask = {
  id: string;
  botId: string;
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
  lastStatus?: 'pending' | 'complete' | 'error';
};

export type ScheduledTaskDraft = Pick<
  ScheduledTask,
  'name' | 'prompt' | 'frequency' | 'dayOfWeek' | 'dayOfMonth' | 'time' | 'timezone' | 'enabled'
>;

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

export type Group = {
  id: string;
  name: string;
  memory: string;
  ownerId: string;
  currentUserId: string;
  isOwner: boolean;
  members: GroupMember[];
  bots: GroupBot[];
  createdAt: string;
  updatedAt: string;
  lastMessage: string;
  lastMessageAt: string;
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

export type Connection = Capability & {
  source: 'user';
  editable: true;
  endpoint: string;
  authType: ConnectionAuthType;
  headerName?: string;
  hasCredential?: boolean;
  connectionStatus: 'connected';
};

export type ConnectionDraft = Pick<Connection, 'name' | 'description' | 'endpoint' | 'authType'> & {
  risk: 'read' | 'interactive';
  headerName: string;
  credential: string;
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
  groups: Group[];
  tools: Capability[];
  skills: Skill[];
};

export type CapabilitySelection = {
  kind: 'skill' | 'tool';
  id: string;
};

export type BotDraft = Pick<Bot, 'name' | 'tagline' | 'color' | 'prompt' | 'toolIds' | 'skillIds'>;
