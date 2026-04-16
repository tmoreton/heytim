// Loads sub-agent profiles (definitions) from $TIM_DIR/agents/*.md
// and .tim/agents/*.md in the current project. Each profile is a markdown
// file with YAML-style frontmatter. Used by spawn_agent and /agents.

import fs from "node:fs";
import path from "node:path";
import os from "node:os";

const timDir = () => process.env.TIM_DIR || path.join(os.homedir(), ".tim");
const timPath = (...parts) => path.join(timDir(), ...parts);

const parseFrontmatter = (src) => {
  const m = src.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
  if (!m) return { meta: {}, body: src.trim() };
  const meta = {};
  const lines = m[1].split("\n");
  let currentKey = null;
  let currentArray = null;
  
  for (const line of lines) {
    // Check for array item (starts with - )
    if (line.match(/^\s+-\s+/) && currentArray !== null) {
      const item = line.replace(/^\s+-\s+/, "").trim();
      if (item) currentArray.push(item);
      continue;
    }
    
    // Check for key: value or key: (start of array)
    const kv = line.match(/^(\w+):\s*(.*)$/);
    if (!kv) continue;
    
    const key = kv[1];
    let v = kv[2].trim();
    
    // Inline array [a, b, c]
    if (v.startsWith("[") && v.endsWith("]")) {
      v = v.slice(1, -1).split(",").map((s) => s.trim()).filter(Boolean);
      meta[key] = v;
      currentArray = null;
    } 
    // Empty value - might be start of multi-line array
    else if (v === "") {
      currentKey = key;
      currentArray = [];
      meta[key] = currentArray;
    } 
    // Simple value
    else {
      meta[key] = v;
      currentArray = null;
    }
  }
  return { meta, body: m[2].trim() };
};

const readDir = (dir) => {
  try {
    return fs.readdirSync(dir).filter((f) => f.endsWith(".md"));
  } catch {
    return [];
  }
};

export function loadAgents() {
  const agents = {};
  const dirs = [
    timPath("agents"),
    path.join(process.cwd(), ".tim", "agents"),
  ];
  for (const dir of dirs) {
    for (const file of readDir(dir)) {
      const full = path.join(dir, file);
      const { meta, body } = parseFrontmatter(fs.readFileSync(full, "utf8"));
      const name = meta.name || path.basename(file, ".md");
      agents[name] = {
        name,
        description: meta.description || "",
        model: meta.model || null,
        tools: Array.isArray(meta.tools) ? meta.tools : null, // null = all
        knowledgeDomain: meta.knowledgeDomain || null,
        knowledgeRefs: Array.isArray(meta.knowledgeRefs) ? meta.knowledgeRefs : null,
        systemPrompt: body,
        source: full,
      };
    }
  }
  return agents;
}
