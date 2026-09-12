const markdownLink = /!?(?:\[([^\]]+)\])\([^\s)]+(?:\s+"[^"]*")?\)/g;
const structuralMarkdown = /(^|\s)(?:#{1,6}|>|[-+*]|\d+[.)])\s+/g;

/** Turn generated Markdown into a stable, plain-text sidebar preview. */
export const messagePreview = (value: string, maximum = 180): string => {
  const clean = value
    .replace(/```[\s\S]*?```/g, (block) => block.replace(/```[^\n]*\n?|```/g, ' '))
    .replace(markdownLink, '$1')
    .replace(/<[^>]+>/g, ' ')
    .replace(structuralMarkdown, '$1')
    .replace(/[*_~`|]+/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!clean) return 'No message preview';
  return clean.length <= maximum ? clean : `${clean.slice(0, maximum - 1).trimEnd()}…`;
};
