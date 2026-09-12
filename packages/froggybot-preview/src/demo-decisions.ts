import type { GroupDecision, Message } from '@froggybot/contracts';
import { withDemoDecisionActions } from './demo-contract';

const decisions = new Map<string, GroupDecision[]>();

export const demoDecisionsForGroup = (groupId: string): GroupDecision[] =>
  (decisions.get(groupId) ?? []).map(withDemoDecisionActions);

export const saveDemoGroupDecision = async (
  groupId: string,
  source: Message | undefined,
): Promise<GroupDecision> => {
  if (!source?.text || source.authorType !== 'bot' || source.status !== 'complete') {
    throw new Error('Only a completed FroggyBot answer can be saved as a decision.');
  }
  const current = decisions.get(groupId) ?? [];
  const existing = current.find((decision) => decision.sourceMessageId === source.id);
  if (existing) return { ...existing };
  const decision: GroupDecision = withDemoDecisionActions({
    id: `decision-${Date.now()}`,
    text: source.text,
    sourceMessageId: source.id,
    sourceAuthorName: source.authorName ?? 'FroggyBot',
    createdById: 'demo-user',
    createdByName: 'You',
    createdAt: new Date().toISOString(),
  });
  decisions.set(groupId, [decision, ...current]);
  return { ...decision };
};

export const deleteDemoGroupDecision = async (groupId: string, decisionId: string): Promise<void> => {
  decisions.set(groupId, (decisions.get(groupId) ?? []).filter((decision) => decision.id !== decisionId));
};
