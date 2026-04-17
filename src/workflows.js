// Workflows are task specs scheduled or invoked on demand. Each workflow
// references an agent (the identity that runs it) and carries the task
// prompt plus optional knobs (precheck tool, tool-allowlist override).
// Memory belongs to the agent, not the workflow — which is what lets us
// have multiple workflows per agent without fragmenting memory.

import fs from "node:fs";
import path from "node:path";
import { timPath, parseFrontmatter } from "./paths.js";

export const getWorkflowsDir = () => timPath("workflows");

export function ensureWorkflowsDir() {
  fs.mkdirSync(getWorkflowsDir(), { recursive: true });
}

export function workflowExists(name) {
  return fs.existsSync(path.join(getWorkflowsDir(), `${name}.md`));
}

export function writeWorkflow(name, { description = "", agent, task = "", precheck = null, tools = null, systemPrompt = "" }) {
  ensureWorkflowsDir();
  const lines = ["---", `name: ${name}`, `description: ${description}`, `agent: ${agent}`];
  if (precheck) lines.push(`precheck: ${precheck}`);
  if (Array.isArray(tools) && tools.length) lines.push(`tools: [${tools.join(", ")}]`);
  if (task) lines.push(`task: ${task.replace(/\n/g, " ")}`);
  lines.push("---", "", systemPrompt);
  const filepath = path.join(getWorkflowsDir(), `${name}.md`);
  fs.writeFileSync(filepath, lines.join("\n") + "\n");
  return filepath;
}

export function deleteWorkflow(name) {
  const p = path.join(getWorkflowsDir(), `${name}.md`);
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

export function loadWorkflows() {
  const workflows = {};
  for (const file of readDir(getWorkflowsDir())) {
    const full = path.join(getWorkflowsDir(), file);
    const { meta, body } = parseFrontmatter(fs.readFileSync(full, "utf8"));
    const name = meta.name || path.basename(file, ".md");
    if (!meta.agent) {
      console.warn(`[workflows] skipping "${name}": missing agent field`);
      continue;
    }
    workflows[name] = {
      name,
      description: meta.description || "",
      agent: meta.agent,
      // The workflow body is the detailed system prompt extension (what the
      // agent should actually do for this task). `task` in frontmatter is a
      // short one-liner used when scheduling; if absent, the body is the task.
      task: typeof meta.task === "string" ? meta.task : "",
      systemPrompt: body,
      precheck: meta.precheck || null,
      tools: Array.isArray(meta.tools) ? meta.tools : null,
      source: full,
    };
  }
  return workflows;
}

// Merge a workflow's task-specific overrides onto its agent's base profile.
// Returns a new profile with combined tools and systemPrompt for a workflow run.
export function mergeProfile(agent, workflow) {
  return {
    ...agent,
    tools: workflow.tools || agent.tools,
    systemPrompt: workflow.systemPrompt
      ? `${agent.systemPrompt}\n\n## Current task — ${workflow.name}\n\n${workflow.systemPrompt}`
      : agent.systemPrompt,
  };
}
