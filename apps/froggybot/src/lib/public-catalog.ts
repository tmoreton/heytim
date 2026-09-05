import { apiUrl } from './cloud';
import type { Capability, PublicCatalog, Skill } from './types';

const repositoryUrl = 'https://github.com/tmoreton/frogbot-capabilities';
const rawCatalogUrl = `${repositoryUrl.replace('github.com', 'raw.githubusercontent.com')}/main/catalog.json`;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value);

const strings = (value: unknown) =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];

const capability = (value: unknown): Capability | undefined => {
  if (!isRecord(value) || typeof value.id !== 'string' || typeof value.name !== 'string' || typeof value.description !== 'string') return;
  const actions = strings(value.actions);
  return {
    id: value.id,
    name: value.name,
    description: value.description,
    provider: typeof value.provider === 'string' ? value.provider : undefined,
    risk:
      value.risk === 'read' || value.risk === 'sandbox' || value.risk === 'interactive'
        ? value.risk
        : undefined,
    category: typeof value.category === 'string' ? value.category : 'General',
    author: typeof value.author === 'string' ? value.author : 'FroggyBot',
    tags: strings(value.tags),
    featured: value.featured === true,
    actions,
  };
};

const skill = (value: unknown): Skill | undefined => {
  const base = capability(value);
  if (!base || !isRecord(value)) return;
  return {
    ...base,
    version: typeof value.version === 'number' ? value.version : 1,
    requiredToolIds: strings(value.requiredToolIds),
    source: 'official',
    visibility: 'public',
    editable: false,
  };
};

const normalizeCatalog = (value: unknown): PublicCatalog => {
  if (!isRecord(value) || !Array.isArray(value.tools) || !Array.isArray(value.skills)) {
    throw new Error('The capability directory returned an invalid response.');
  }
  const tools = value.tools
    .filter((item) => !isRecord(item) || item.enabled !== false)
    .map(capability)
    .filter((item): item is Capability => Boolean(item));
  const toolIds = new Set(tools.map((item) => item.id));
  const skills = value.skills
    .map(skill)
    .filter((item): item is Skill => Boolean(item))
    .filter((item) => item.requiredToolIds.every((id) => toolIds.has(id)));
  return {
    skills,
    tools,
    repositoryUrl: typeof value.repositoryUrl === 'string' ? value.repositoryUrl : repositoryUrl,
    contributionUrl:
      typeof value.contributionUrl === 'string'
        ? value.contributionUrl
        : `${repositoryUrl}/blob/main/CONTRIBUTING.md`,
  };
};

const fetchCatalog = async (url: string) => {
  const response = await fetch(url, { headers: { accept: 'application/json' } });
  if (!response.ok) throw new Error(`The capability directory is unavailable (${response.status}).`);
  return normalizeCatalog(await response.json());
};

export async function loadPublicCatalog(): Promise<PublicCatalog> {
  try {
    return await fetchCatalog(`${apiUrl}/public/catalog`);
  } catch {
    return fetchCatalog(rawCatalogUrl);
  }
}
