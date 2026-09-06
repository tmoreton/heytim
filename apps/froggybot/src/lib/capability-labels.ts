import type { Capability } from './types';

export const providerLabel = (provider?: string): string => {
  if (provider === 'gmail') return 'Google';
  if (provider === 'mcp') return 'Private connection';
  if (provider === 'agentcore-gateway') return 'Connected service';
  return 'Built-in';
};

export const requiredToolLabels = (ids: string[], tools: Capability[]): string[] => {
  const names = new Map(tools.map((tool) => [tool.id, tool.name]));
  const visible: string[] = [];
  let internal = 0;
  ids.forEach((id) => {
    const name = names.get(id);
    if (name) visible.push(name);
    else internal += 1;
  });
  if (internal) visible.push(internal === 1 ? 'Built-in helper' : `${internal} built-in helpers`);
  return visible;
};
