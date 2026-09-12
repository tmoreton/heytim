import type { Capability } from './types';

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
