export type Bot = {
  id: string;
  name: string;
  tagline: string;
  color: string;
  prompt: string;
  toolIds: string[];
  skillIds: string[];
  createdAt: string;
  updatedAt: string;
  lastMessage: string;
  lastMessageAt: string;
};

export type Message = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  createdAt: string;
  status: 'complete' | 'pending' | 'error';
};

export type Capability = {
  id: string;
  name: string;
  description: string;
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
  tools: Capability[];
  skills: Skill[];
};

export type BotDraft = Pick<Bot, 'name' | 'tagline' | 'color' | 'prompt' | 'toolIds' | 'skillIds'>;
