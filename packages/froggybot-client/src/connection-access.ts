import type { Capability, Connection, ConnectionProvider } from '@froggybot/contracts';

export type CapabilityAccessLabel = 'Included' | 'Connected';

export type ConnectionProviderFamily = {
  id: string;
  name: string;
  description: string;
  iconText: string;
  logoProviderId: string;
  includedSummary?: string;
  includedToolIds: string[];
  grouped: boolean;
  providers: ConnectionProvider[];
};

export type ConnectionProviderToolGroup = {
  family: ConnectionProviderFamily;
  tools: Capability[];
};

export const isUserConnection = (capability: Capability): capability is Connection =>
  capability.source === 'user'
  && capability.editable === true
  && typeof (capability as Connection).provider === 'string'
  && typeof (capability as Connection).connectionStatus === 'string';

export const catalogTools = (capabilities: Capability[]): Capability[] =>
  capabilities.filter((capability) => !isUserConnection(capability));

export const userConnections = (capabilities: Capability[]): Connection[] =>
  capabilities.filter(isUserConnection);

export const connectionProviderFamilies = (
  providers: ConnectionProvider[],
): ConnectionProviderFamily[] => {
  const families = new Map<string, ConnectionProviderFamily>();
  for (const provider of providers) {
    const id = provider.familyId ?? provider.id;
    const existing = families.get(id);
    if (existing) {
      existing.providers.push(provider);
      continue;
    }
    families.set(id, {
      id,
      name: provider.familyName ?? provider.name,
      description: provider.familyDescription ?? provider.description,
      iconText: provider.familyIconText ?? provider.iconText,
      logoProviderId: provider.familyLogoProviderId ?? provider.id,
      includedSummary: provider.familyIncludedSummary,
      includedToolIds: provider.familyIncludedToolIds ?? [],
      grouped: provider.familyId !== undefined,
      providers: [provider],
    });
  }
  return [...families.values()];
};

export const connectionProviderToolGroups = (
  tools: Capability[],
  providers: ConnectionProvider[],
): { groups: ConnectionProviderToolGroup[]; ungrouped: Capability[] } => {
  const groupedToolIds = new Set<string>();
  const groups = connectionProviderFamilies(providers).flatMap((family) => {
    if (!family.grouped) return [];
    const providerIds = new Set(family.providers.map((provider) => provider.id));
    const includedToolIds = new Set(family.includedToolIds);
    const familyTools = tools.filter(
      (tool) => includedToolIds.has(tool.id) || (tool.provider ? providerIds.has(tool.provider) : false),
    );
    for (const tool of familyTools) groupedToolIds.add(tool.id);
    return familyTools.length ? [{ family, tools: familyTools }] : [];
  });
  return {
    groups,
    ungrouped: tools.filter((tool) => !groupedToolIds.has(tool.id)),
  };
};

export const capabilityAccessLabel = (capability: Capability): CapabilityAccessLabel => {
  if (!isUserConnection(capability)) return 'Included';
  return 'Connected';
};
