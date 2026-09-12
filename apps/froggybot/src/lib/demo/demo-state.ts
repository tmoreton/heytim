import type {
  Attachment,
  Bot,
  BotDocument,
  Connection,
  Group,
  Message,
  ScheduleRun,
  ScheduledTask,
  SkillDetail,
} from '../types';
import { createDemoTripMessages } from '../demo-trip-brief';
import { createInitialDemoGroups, createInitialDemoSchedules } from '../demo-fixtures';

export const demoTimestamp = new Date().toISOString();

export const demoState = {
  bots: [] as Bot[],
  initialCatalogLoaded: false,
  groups: createInitialDemoGroups(demoTimestamp),
  schedules: createInitialDemoSchedules(demoTimestamp),
  personalSkills: [] as SkillDetail[],
  personalConnections: [] as Connection[],
  uploadedAttachments: new Map<string, Attachment>(),
  scheduleRuns: [] as ScheduleRun[],
  messages: new Map<string, Message[]>([
    [
      'chief',
      [{
        id: 'welcome-chief',
        role: 'assistant',
        text: 'I am caught up. What should we move forward today?',
        createdAt: demoTimestamp,
        status: 'complete',
      }],
    ],
    ['trip-planner', []],
    ['event-planner', []],
    ['research-reports', []],
  ]),
  botDocuments: new Map<string, BotDocument[]>([
    [
      'chief',
      [{
        id: 'demo-launch-checklist',
        name: 'launch-checklist.docx',
        size: 48_200,
        kind: 'document',
        format: 'docx',
        contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        createdAt: demoTimestamp,
      }],
    ],
    [
      'research-reports',
      [
        {
          id: 'demo-market-brief',
          name: 'market-research-brief.pdf',
          size: 284_300,
          kind: 'document',
          format: 'pdf',
          contentType: 'application/pdf',
          createdAt: demoTimestamp,
        },
        {
          id: 'demo-source-data',
          name: 'source-data.xlsx',
          size: 91_700,
          kind: 'document',
          format: 'xlsx',
          contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          createdAt: demoTimestamp,
        },
      ],
    ],
  ]),
  groupMessages: new Map<string, Message[]>([
    ['launch-room', createDemoTripMessages(demoTimestamp)],
  ]),
};

export const processingMessage = (items: Message[]) => (
  [...items].reverse().find((message) => ['pending', 'running'].includes(message.status))
);

export const cloneGroup = (group: Group): Group => ({
  ...group,
  members: [...group.members],
  bots: [...group.bots],
  decisions: [...group.decisions],
});

export const removeBotFromDemoState = (botId: string): void => {
  demoState.bots = demoState.bots.filter((bot) => bot.id !== botId);
  demoState.schedules = demoState.schedules.filter((task: ScheduledTask) => task.botId !== botId);
  demoState.messages.delete(botId);
  demoState.botDocuments.delete(botId);
  demoState.groups = demoState.groups.map((group) => ({
    ...group,
    bots: group.bots.filter((bot) => bot.id !== botId),
  }));
};
