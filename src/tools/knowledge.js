// Knowledge base tools for agents to read/write shared knowledge

import {
  listDomains,
  listKnowledge,
  searchKnowledge,
  readKnowledge,
  readKnowledgeRefs,
  writeKnowledge,
  appendKnowledge,
} from "../knowledge.js";

export const listDomainsSchema = {
  type: "function",
  function: {
    name: "list_knowledge_domains",
    description: "List all knowledge domains (categories) available in the knowledge base",
    parameters: { type: "object", properties: {} },
  },
};

export const listKnowledgeSchema = {
  type: "function",
  function: {
    name: "list_knowledge",
    description: "List all knowledge files in a specific domain with metadata (description, tags, load behavior)",
    parameters: {
      type: "object",
      properties: {
        domain: { type: "string", description: "Knowledge domain (e.g., 'youtube', 'twitter')" },
        tags: { type: "array", items: { type: "string" }, description: "Filter by tags" },
        provides: { type: "array", items: { type: "string" }, description: "Filter by what files provide (e.g., 'voice', 'metrics')" },
      },
      required: ["domain"],
    },
  },
};

export const searchKnowledgeSchema = {
  type: "function",
  function: {
    name: "search_knowledge",
    description: "Search across ALL knowledge domains for files matching query, tags, or provides. Use when you need knowledge from outside your primary domain (e.g., youtube agent needs twitter research patterns).",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string", description: "Search in name/description" },
        tags: { type: "array", items: { type: "string" }, description: "Filter by tags" },
        provides: { type: "array", items: { type: "string" }, description: "Filter by what files provide" },
        domains: { type: "array", items: { type: "string" }, description: "Limit to specific domains" },
      },
    },
  },
};

export const readKnowledgeSchema = {
  type: "function",
  function: {
    name: "read_knowledge",
    description: "Read a specific knowledge file. Use format: domain/name (e.g., 'youtube/channel-profile')",
    parameters: {
      type: "object",
      properties: {
        ref: { 
          type: "string", 
          description: "Knowledge reference in 'domain/name' format" 
        },
      },
      required: ["ref"],
    },
  },
};

export const readMultipleKnowledgeSchema = {
  type: "function",
  function: {
    name: "read_knowledge_multi",
    description: "Read multiple knowledge files at once. Useful for gathering context from different domains.",
    parameters: {
      type: "object",
      properties: {
        refs: { 
          type: "array", 
          items: { type: "string" },
          description: "Array of refs in 'domain/name' format" 
        },
      },
      required: ["refs"],
    },
  },
};

export const writeKnowledgeSchema = {
  type: "function",
  function: {
    name: "write_knowledge",
    description: "Create or overwrite a knowledge file. Use for structured information.",
    parameters: {
      type: "object",
      properties: {
        domain: { type: "string", description: "Knowledge domain" },
        name: { type: "string", description: "Knowledge file name" },
        description: { type: "string", description: "Brief description" },
        tags: { type: "array", items: { type: "string" }, description: "Tags for organization" },
        load: { 
          type: "string", 
          description: "Load behavior: 'auto', 'manual', or specific refs" 
        },
        provides: { type: "array", items: { type: "string" }, description: "What this file provides (e.g., 'voice', 'metrics')" },
        body: { type: "string", description: "Markdown content" },
      },
      required: ["domain", "name", "body"],
    },
  },
};

export const appendKnowledgeSchema = {
  type: "function",
  function: {
    name: "append_knowledge",
    description: "Append a section to an existing knowledge file. Use for logging results, test outcomes, or new insights.",
    parameters: {
      type: "object",
      properties: {
        ref: { type: "string", description: "Knowledge ref in 'domain/name' format" },
        section: { type: "string", description: "Section heading (e.g., 'AB Test Results')" },
        content: { type: "string", description: "Markdown content to append" },
      },
      required: ["ref", "section", "content"],
    },
  },
};

// Run functions
export async function listDomainsRun() {
  const domains = listDomains();
  if (!domains.length) return "(no knowledge domains yet — create one with write_knowledge)";
  return domains.map(d => `- ${d}`).join("\n");
}

export async function listKnowledgeRun({ domain, tags = [], provides = [] }) {
  let files = listKnowledge(domain);
  if (tags.length) files = files.filter(f => tags.some(t => f.tags.includes(t)));
  if (provides.length) files = files.filter(f => provides.some(p => f.provides?.includes(p)));
  
  if (!files.length) return `(no knowledge files in '${domain}' domain${tags.length ? ' with tags: ' + tags.join(', ') : ''})`;
  
  const lines = files.map(f => {
    const load = f.load !== "manual" ? ` [load: ${Array.isArray(f.load) ? f.load.join(",") : f.load}]` : "";
    const provides = f.provides?.length ? ` [provides: ${f.provides.join(",")}]` : "";
    const tags = f.tags?.length ? ` {${f.tags.join(", ")}}` : "";
    const desc = f.description ? ` — ${f.description}` : "";
    return `- **${f.fullName}**${load}${provides}${tags}${desc}`;
  });
  return lines.join("\n");
}

export async function searchKnowledgeRun({ query = "", tags = [], provides = [], domains = [] }) {
  const results = searchKnowledge(query, { tags, provides, domains });
  if (!results.length) return `(no knowledge files matching criteria)`;
  
  const lines = results.map(f => {
    const provides = f.provides?.length ? ` [provides: ${f.provides.join(",")}]` : "";
    const tags = f.tags?.length ? ` {${f.tags.join(", ")}}` : "";
    const desc = f.description ? ` — ${f.description}` : "";
    return `- **${f.fullName}**${provides}${tags}${desc}`;
  });
  return lines.join("\n");
}

export async function readKnowledgeRun({ ref }) {
  const [domain, ...nameParts] = ref.split("/");
  const name = nameParts.join("/");
  const data = readKnowledge(domain, name);
  if (!data) return `ERROR: knowledge file '${ref}' not found`;
  
  const tags = data.meta.tags?.length ? `\nTags: ${data.meta.tags.join(", ")}` : "";
  const provides = data.meta.provides?.length ? `\nProvides: ${data.meta.provides.join(", ")}` : "";
  const desc = data.meta.description ? `\nDescription: ${data.meta.description}` : "";
  return `${desc}${tags}${provides}\n\n---\n\n${data.body}`;
}

export async function readMultipleKnowledgeRun({ refs }) {
  const items = readKnowledgeRefs(refs);
  if (!items.length) return "ERROR: no knowledge files found for the given refs";
  
  return items.map(data => {
    const header = `\n=== ${data.fullName} ===\n`;
    return header + data.body;
  }).join("\n\n");
}

export async function writeKnowledgeRun({ domain, name, description = "", tags = [], load = "manual", provides = [], body = "" }) {
  const filepath = writeKnowledge(domain, name, { description, tags, load, provides, body });
  return `Created knowledge file: ${filepath}`;
}

export async function appendKnowledgeRun({ ref, section, content }) {
  const [domain, ...nameParts] = ref.split("/");
  const name = nameParts.join("/");
  const filepath = appendKnowledge(domain, name, section, content);
  return `Appended to ${ref}.md`;
}
