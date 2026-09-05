import type { Capability, Skill, SkillDetail } from './types';

const CATALOG_URL = 'https://froggybot.com/catalog.json';
const CATALOG_REPOSITORY = 'tmoreton/frogbot-skills';

type CatalogSkill = Skill & { path: string };
type DemoCatalog = { tools: Capability[]; skills: Skill[] };

let catalogRequest: Promise<DemoCatalog> | undefined;
let catalogSkills = new Map<string, CatalogSkill>();

const shortText = (value: unknown, fallback = ''): string =>
  typeof value === 'string' ? value : fallback;

const stringList = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];

const publicMetadata = (value: Record<string, unknown>) => ({
  category: shortText(value.category) || undefined,
  author: shortText(value.author) || undefined,
  tags: stringList(value.tags),
  featured: value.featured === true,
});

const fetchCatalog = async (): Promise<DemoCatalog> => {
  const response = await fetch(CATALOG_URL, { headers: { accept: 'application/json' } });
  if (!response.ok) throw new Error('The public capability library is unavailable.');
  const value: unknown = await response.json();
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('The public capability library is invalid.');
  }
  const catalog = value as Record<string, unknown>;
  if (
    catalog.schemaVersion !== 2 ||
    catalog.repository !== CATALOG_REPOSITORY ||
    !Array.isArray(catalog.tools) ||
    !Array.isArray(catalog.skills)
  ) {
    throw new Error('The public capability library is invalid.');
  }

  const tools = catalog.tools.flatMap((raw): Capability[] => {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return [];
    const item = raw as Record<string, unknown>;
    const id = shortText(item.id);
    const name = shortText(item.name);
    const description = shortText(item.description);
    if (!id || !name || !description || item.enabled !== true) return [];
    return [{
      id,
      name,
      description,
      provider: shortText(item.provider) || undefined,
      risk: item.risk === 'read' || item.risk === 'sandbox' || item.risk === 'interactive'
        ? item.risk
        : undefined,
      actions: stringList(item.actions),
      ...publicMetadata(item),
    }];
  });
  const toolIds = new Set(tools.map((tool) => tool.id));

  const listedSkills = catalog.skills.flatMap((raw): CatalogSkill[] => {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return [];
    const item = raw as Record<string, unknown>;
    const id = shortText(item.id);
    const name = shortText(item.name);
    const description = shortText(item.description);
    const path = shortText(item.path);
    const requiredToolIds = stringList(item.requiredToolIds);
    if (
      !id ||
      !name ||
      !description ||
      !Number.isInteger(item.version) ||
      path !== `skills/${id}/SKILL.md` ||
      !requiredToolIds.every((toolId) => toolIds.has(toolId))
    ) return [];
    return [{
      id,
      version: item.version as number,
      name,
      description,
      path,
      requiredToolIds,
      source: 'official',
      visibility: 'public',
      editable: false,
      ...publicMetadata(item),
    }];
  });
  catalogSkills = new Map(listedSkills.map((skill) => [skill.id, skill]));
  return {
    tools,
    skills: listedSkills.map(({ path: _path, ...skill }) => skill),
  };
};

export const loadDemoCatalog = async (): Promise<DemoCatalog> => {
  catalogRequest ??= fetchCatalog().catch((error) => {
    catalogRequest = undefined;
    throw error;
  });
  return catalogRequest;
};

export const loadDemoSkill = async (skillId: string): Promise<SkillDetail> => {
  await loadDemoCatalog();
  const skill = catalogSkills.get(skillId);
  if (!skill) throw new Error('Skill not found.');
  const response = await fetch(new URL(skill.path, CATALOG_URL));
  if (!response.ok) throw new Error('The skill instructions are unavailable.');
  const document = await response.text();
  const boundary = document.startsWith('---\n') ? document.indexOf('\n---\n', 4) : -1;
  const instructions = boundary >= 0 ? document.slice(boundary + 5).trim() : '';
  if (!instructions) throw new Error('The skill instructions are invalid.');
  const { path: _path, ...metadata } = skill;
  return { ...metadata, instructions };
};
