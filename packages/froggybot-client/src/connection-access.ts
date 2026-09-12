import type { Capability, Connection } from '@froggybot/contracts';

export type CapabilityAccessLabel = 'Included' | 'Connected' | 'Legacy connection';

export const isUserConnection = (capability: Capability): capability is Connection =>
  capability.source === 'user'
  && capability.editable === true
  && typeof (capability as Connection).endpoint === 'string';

export const catalogTools = (capabilities: Capability[]): Capability[] =>
  capabilities.filter((capability) => !isUserConnection(capability));

export const userConnections = (capabilities: Capability[]): Connection[] =>
  capabilities.filter(isUserConnection);

export const capabilityAccessLabel = (capability: Capability): CapabilityAccessLabel => {
  if (!isUserConnection(capability)) return 'Included';
  return capability.authType === 'oauth' ? 'Connected' : 'Legacy connection';
};
