export type Bot = {
  id: string;
  name: string;
  tagline: string;
  color: string;
  prompt: string;
  toolIds: string[];
  extraToolIds?: string[];
  skillIds: string[];
  createdAt: string;
  updatedAt: string;
  lastMessage: string;
  lastMessageAt: string;
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
  roundId?: string;
  roundPosition?: number;
  roundSize?: number;
  roundRole?: 'solo' | 'lead' | 'contributor' | 'synthesizer';
  createdAt: string;
  status: 'complete' | 'waiting' | 'pending' | 'error';
};

export type ScheduleFrequency = 'daily' | 'weekly';

export type ScheduledTask = {
  id: string;
  botId: string;
  name: string;
  prompt: string;
  frequency: ScheduleFrequency;
  dayOfWeek?: string;
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
  'name' | 'prompt' | 'frequency' | 'dayOfWeek' | 'time' | 'timezone' | 'enabled'
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
};

export type Group = {
  id: string;
  name: string;
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

export type GroupDraft = Pick<Group, 'name'> & { botIds: string[] };

export type InviteKind = 'bot' | 'chat' | 'group' | 'skill';

export type Invitation = {
  kind: InviteKind;
  token: string;
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

export type BotDraft = Pick<Bot, 'name' | 'tagline' | 'color' | 'prompt' | 'toolIds' | 'skillIds'>;
