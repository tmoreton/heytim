import type { Bot, BotDraft, Capability, CapabilitySelection, Skill } from '../../lib/types';

const uniqueKnownIds = (ids: string[], knownIds: Set<string>) => (
  [...new Set(ids.filter((id) => knownIds.has(id)))]
);

export const createBotDraft = (
  bot: Bot | undefined,
  skills: Skill[],
  tools: Capability[],
  defaultColor: string,
  suggested?: CapabilitySelection,
): BotDraft => {
  const knownSkillIds = new Set(skills.map((skill) => skill.id));
  const knownToolIds = new Set(tools.map((tool) => tool.id));
  const selectedSkillIds = bot ? uniqueKnownIds(bot.skillIds, knownSkillIds) : [];
  const requiredToolIds = new Set(
    skills
      .filter((skill) => selectedSkillIds.includes(skill.id))
      .flatMap((skill) => skill.requiredToolIds),
  );
  const extraToolIds = bot
    ? uniqueKnownIds(
        bot.extraToolIds ?? bot.toolIds.filter((toolId) => !requiredToolIds.has(toolId)),
        knownToolIds,
      )
    : [];
  const effectiveToolIds = new Set([...extraToolIds, ...requiredToolIds]);
  const draft: BotDraft = bot
    ? {
        name: bot.name,
        tagline: bot.tagline,
        prompt: bot.prompt,
        color: bot.color,
        toolIds: extraToolIds,
        alwaysAllowedToolIds: uniqueKnownIds(
          (bot.alwaysAllowedToolIds ?? []).filter((id) => effectiveToolIds.has(id)),
          knownToolIds,
        ),
        skillIds: selectedSkillIds,
      }
    : {
        name: '',
        tagline: '',
        prompt: '',
        color: defaultColor,
        toolIds: [],
        alwaysAllowedToolIds: [],
        skillIds: [],
      };

  if (suggested?.kind === 'skill' && knownSkillIds.has(suggested.id)) {
    return { ...draft, skillIds: [...new Set([...draft.skillIds, suggested.id])] };
  }
  if (suggested?.kind === 'tool' && knownToolIds.has(suggested.id)) {
    return { ...draft, toolIds: [...new Set([...draft.toolIds, suggested.id])] };
  }
  return draft;
};
