import type { SkillDetail, SkillDraft } from '../types';
import { loadDemoCatalog, loadDemoSkill } from '../demo-catalog';

import { demoState } from './demo-state';

export const demoGetSkill = async (skillId: string): Promise<SkillDetail> => {
  const personal = demoState.personalSkills.find((item) => item.id === skillId);
  return personal ? { ...personal } : loadDemoSkill(skillId);
};

export const demoSaveSkill = async (draft: SkillDraft, skillId?: string): Promise<SkillDetail> => {
  const existing = demoState.personalSkills.find((item) => item.id === skillId);
  if (skillId && (!existing || !existing.editable)) {
    throw new Error('Only your own skills can be edited.');
  }
  const saved: SkillDetail = {
    ...draft,
    id: existing?.id ?? `skill-${Date.now()}`,
    version: (existing?.version ?? 0) + 1,
    source: 'user',
    editable: true,
    relationship: 'owner',
    updatedAt: new Date().toISOString(),
  };
  demoState.personalSkills = existing
    ? demoState.personalSkills.map((item) => (item.id === saved.id ? saved : item))
    : [...demoState.personalSkills, saved];
  return saved;
};

export const demoDeleteConnection = (connectionId: string): void => {
  const inUse = demoState.bots.some((bot) => bot.toolIds.includes(connectionId));
  if (inUse) throw new Error('Remove this connection from its FroggyBot before deleting it.');
  demoState.personalConnections = demoState.personalConnections.filter(
    (item) => item.id !== connectionId,
  );
};

export const demoImportSkill = async (_token: string): Promise<SkillDetail> => {
  const catalog = await loadDemoCatalog();
  const first = catalog.skills[0];
  if (!first) throw new Error('No public skills are available.');
  return { ...(await loadDemoSkill(first.id)), relationship: 'installed' };
};
