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

export type Bootstrap = {
  bots: Bot[];
  tools: Capability[];
  skills: Capability[];
};

export type BotDraft = Pick<Bot, 'name' | 'tagline' | 'color' | 'prompt' | 'toolIds' | 'skillIds'>;
