export type Entry = {
  id: string; name: string; category: string; author: string; tags: string[];
  featured?: boolean; description?: string; tagline?: string; color?: string;
};
export type Skill = Entry & { requiredToolIds: string[]; path: string; version: number };
export type Bot = Entry & { skillIds: string[]; toolIds?: string[]; version: number };
export type Catalog = { skills: Skill[]; bots: Bot[]; tools: { id: string; enabled: boolean }[] };

export function availableEntries(catalog: Catalog) {
  const tools = new Set(catalog.tools.filter((tool) => tool.enabled).map((tool) => tool.id));
  const skills = catalog.skills.filter((skill) => skill.requiredToolIds.every((id) => tools.has(id)));
  const skillIds = new Set(skills.map((skill) => skill.id));
  const bots = catalog.bots.filter((bot) => bot.skillIds.every((id) => skillIds.has(id))
    && (bot.toolIds ?? []).every((id) => tools.has(id)));
  return { skills, bots };
}

export function filterEntries<T extends Entry>(entries: T[], query: string, category: string): T[] {
  const needle = query.trim().toLocaleLowerCase();
  return entries.filter((item) => (category === 'All' || item.category === category)
    && [item.name, item.tagline, item.description, item.category, ...item.tags]
      .filter(Boolean).join(' ').toLocaleLowerCase().includes(needle))
    .sort((a, b) => Number(Boolean(b.featured)) - Number(Boolean(a.featured)) || a.name.localeCompare(b.name));
}

export function invitationAppLink(search: string): string | undefined {
  const params = new URLSearchParams(search);
  const kind = params.get('kind');
  const value = params.get('token');
  if (!kind || !['group', 'bot', 'skill', 'chat'].includes(kind) || !value) return undefined;
  if (params.getAll('kind').length !== 1 || params.getAll('token').length !== 1) return undefined;
  if (value.length > 2048 || /[\s\x00-\x1f]/.test(value)) return undefined;
  return `frogbot://invite?${new URLSearchParams({ kind, token: value })}`;
}
