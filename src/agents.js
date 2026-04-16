// Agents are persistent identities at $TIM_DIR/agents/*.md. Each agent owns
// a memory file (one per agent, bootstrapped at creation). Agents orchestrate
// workflows via spawn_workflow. Workflows — the task specs agents run — live
// separately in $TIM_DIR/workflows/ (see workflows.js).

import fs from "node:fs";
import path from "node:path";
import { timPath, parseFrontmatter } from "./paths.js";
import { bootstrapMemory } from "./memory.js";

export const getAgentsDir = () => timPath("agents");

export function ensureAgentsDir() {
  fs.mkdirSync(getAgentsDir(), { recursive: true });
}

export function agentExists(name) {
  return fs.existsSync(path.join(getAgentsDir(), `${name}.md`));
}

export function writeAgentProfile(name, { description = "", tools = null, systemPrompt = "" }) {
  ensureAgentsDir();
  const lines = ["---", `name: ${name}`, `description: ${description}`];
  if (tools && tools !== "all") lines.push(`tools: [${tools}]`);
  lines.push("---", "", systemPrompt);
  const filepath = path.join(getAgentsDir(), `${name}.md`);
  fs.writeFileSync(filepath, lines.join("\n") + "\n");
  bootstrapMemory(name, { description });
  return filepath;
}

export function deleteAgentProfile(name) {
  const p = path.join(getAgentsDir(), `${name}.md`);
  if (!fs.existsSync(p)) return false;
  fs.unlinkSync(p);
  return true;
}

const readDir = (dir) => {
  try {
    return fs.readdirSync(dir).filter((f) => f.endsWith(".md"));
  } catch {
    return [];
  }
};

export function loadAgents() {
  const agents = {};
  const dirs = [getAgentsDir(), path.join(process.cwd(), ".tim", "agents")];
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
        systemPrompt: body,
        source: full,
      };
    }
  }
  return agents;
}
