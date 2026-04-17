// spawn_swarm: Run multiple agents/workflows in parallel with shared scratchpad
// and automatic synthesis of results.

// Dynamic imports to break circular dependency with react.js
let _createAgent = null;
async function getCreateAgent() {
  if (!_createAgent) {
    const { createAgent } = await import("../react.js");
    _createAgent = createAgent;
  }
  return _createAgent;
}

import { loadWorkflows } from "../workflows.js";
import { loadAgents } from "../agents.js";
import { complete } from "../llm.js";
import * as ui from "../ui.js";

// Shared scratchpad for active swarm — single-threaded so this is safe
export class SwarmScratchpad {
  constructor() {
    this.store = new Map();
  }

  read(key) {
    if (key) {
      return this.store.get(key) ?? `[key "${key}" not found]`;
    }
    if (this.store.size === 0) return "[scratchpad is empty]";
    return [...this.store.entries()].map(([k, v]) => `${k}: ${v}`).join("\n");
  }

  write(key, value, append = false) {
    if (append) {
      const existing = this.store.get(key) || "";
      this.store.set(key, existing ? `${existing}\n${value}` : value);
      return `Appended to scratchpad: ${key}`;
    }
    this.store.set(key, value);
    return `Written to scratchpad: ${key}`;
  }

  dump() {
    return this.read();
  }
}

let activeScratchpad = null;

export function getActiveScratchpad() {
  return activeScratchpad;
}

// Tool definitions injected into swarm agents
export function getScratchpadToolDefs() {
  return [
    {
      type: "function",
      function: {
        name: "swarm_scratchpad_read",
        description:
          "Read from the shared swarm scratchpad. Other agents in this swarm can also read/write here. Use to check what other agents have found or to avoid duplicate work. Omit key to read all entries.",
        parameters: {
          type: "object",
          properties: {
            key: { type: "string", description: "Key to read (omit for all entries)" },
          },
        },
      },
    },
    {
      type: "function",
      function: {
        name: "swarm_scratchpad_write",
        description:
          "Write a finding or result to the shared swarm scratchpad so other agents can see it. Use descriptive keys like 'frontend_analysis' or 'auth_issues_found'.",
        parameters: {
          type: "object",
          properties: {
            key: { type: "string", description: "Descriptive key (e.g. 'security_findings')" },
            value: { type: "string", description: "Content to store" },
            append: { type: "boolean", description: "Append instead of replace" },
          },
          required: ["key", "value"],
        },
      },
    },
  ];
}

// Execute scratchpad tool calls
export function handleScratchpadTool(name, args) {
  const pad = activeScratchpad;
  if (!pad) return "[No active swarm scratchpad]";

  if (name === "swarm_scratchpad_read") {
    return pad.read(args.key);
  }
  if (name === "swarm_scratchpad_write") {
    return pad.write(args.key, args.value, args.append);
  }
  return null;
}

// Tools blocked in swarm agents to prevent recursive spawning
const BLOCKED_TOOLS = new Set(["spawn_agent", "spawn_swarm", "spawn_workflow"]);

function filterTools(toolsList) {
  if (!toolsList || toolsList === "all") return undefined;
  return toolsList.filter((t) => !BLOCKED_TOOLS.has(t));
}

// Spawn a single agent by type (agent ID) or workflow
async function spawnOne(agentOrWorkflow, task, index) {
  const createAgent = await getCreateAgent();
  const workflows = loadWorkflows();
  const agents = loadAgents();

  // Check if it's a workflow reference
  if (workflows[agentOrWorkflow]) {
    const w = workflows[agentOrWorkflow];
    const agent = agents[w.agent];
    if (!agent) {
      throw new Error(`Workflow "${agentOrWorkflow}" references unknown agent "${w.agent}"`);
    }
    const subProfile = {
      ...agent,
      tools: filterTools(w.tools || agent.tools),
      systemPrompt: w.systemPrompt
        ? `${agent.systemPrompt}\n\n## Current task — ${agentOrWorkflow}\n\n${w.systemPrompt}\n\nYou are running inside a swarm. Use swarm_scratchpad_read/write to coordinate with other agents. You do NOT have access to spawn other agents or swarms.`
        : `${agent.systemPrompt}\n\n## Current task — ${agentOrWorkflow}\n\nYou are running inside a swarm. Use swarm_scratchpad_read/write to coordinate with other agents. You do NOT have access to spawn other agents or swarms.`,
    };
    const sub = await createAgent(subProfile);
    await sub.turn(task, { aborted: false });
    const last = sub.state.messages
      .filter((m) => m.role === "assistant" && !m.tool_calls?.length && m.content)
      .pop();
    return last?.content || "";
  }

  // Check if it's a direct agent reference
  if (agents[agentOrWorkflow]) {
    const agent = agents[agentOrWorkflow];
    const subProfile = {
      ...agent,
      tools: filterTools(agent.tools),
      systemPrompt: agent.systemPrompt
        ? `${agent.systemPrompt}\n\nYou are running inside a swarm. Use swarm_scratchpad_read/write to coordinate with other agents. You do NOT have access to spawn other agents or swarms.`
        : "You are running inside a swarm. Use swarm_scratchpad_read/write to coordinate with other agents. You do NOT have access to spawn other agents or swarms.",
    };
    const sub = await createAgent(subProfile);
    await sub.turn(task, { aborted: false });
    const last = sub.state.messages
      .filter((m) => m.role === "assistant" && !m.tool_calls?.length && m.content)
      .pop();
    return last?.content || "";
  }

  throw new Error(`Unknown agent or workflow: "${agentOrWorkflow}"`);
}

// Synthesize results from multiple agents into a unified summary
async function synthesizeResults(results, customPrompt) {
  const succeeded = results.filter((r) => r.status === "fulfilled");
  if (succeeded.length === 0) return "";

  const agentOutputs = succeeded
    .map((r) => `## ${r.agent}\n**Task:** ${r.task}\n\n${r.output}`)
    .join("\n\n---\n\n");

  const scratchpad = activeScratchpad?.dump() || "";
  const scratchpadSection = scratchpad && scratchpad !== "[scratchpad is empty]"
    ? `\n\n## Shared Scratchpad\n${scratchpad}`
    : "";

  const prompt = customPrompt || `You are synthesizing results from ${succeeded.length} parallel agents.

Combine their findings into a single, coherent summary:
- Merge overlapping findings
- Highlight agreements and contradictions
- Organize by theme, not by agent
- Call out key insights and actionable items
- Be concise — synthesize, don't repeat

${agentOutputs}${scratchpadSection}`;

  try {
    const response = await complete({
      model: process.env.TIM_MODEL || "accounts/fireworks/routers/kimi-k2p5-turbo",
      messages: [
        {
          role: "system",
          content: "You synthesize outputs from multiple parallel agents into a unified, actionable summary. Be concise and structured.",
        },
        { role: "user", content: prompt },
      ],
      max_tokens: 4096,
    });
    return response.content || "";
  } catch (err) {
    ui.info(`  ⚠ Synthesis failed: ${err.message}`);
    return "";
  }
}

// Main swarm runner
export async function runSwarm(tasks, options = {}) {
  if (!tasks || tasks.length === 0) {
    return "No tasks provided to the swarm.";
  }

  if (tasks.length === 1) {
    return spawnOne(tasks[0].agent, tasks[0].task, 0);
  }

  const shouldSynthesize = options.synthesize !== false;
  const { signal } = options;

  if (signal?.aborted) {
    throw new Error("Swarm aborted");
  }

  ui.info(`\n  🐝 Swarm launching ${tasks.length} agents in parallel...\n`);

  // Initialize scratchpad
  activeScratchpad = new SwarmScratchpad();
  const startTime = Date.now();

  // Launch all agents concurrently
  const promises = tasks.map((t, i) =>
    spawnOne(t.agent, t.task, i).then(
      (output) => ({ status: "fulfilled", output }),
      (error) => ({ status: "rejected", error: error.message })
    )
  );

  const settled = await Promise.allSettled(promises);
  const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);

  const results = settled.map((result, i) => ({
    agent: tasks[i].agent,
    task: tasks[i].task,
    status: result.status,
    output: result.status === "fulfilled" ? result.value : `Error: ${result.reason?.error || "Unknown error"}`,
  }));

  const succeeded = results.filter((r) => r.status === "fulfilled").length;
  const failed = results.filter((r) => r.status === "rejected").length;

  ui.info(`  🐝 Swarm complete: ${succeeded} succeeded, ${failed} failed (${elapsed}s)\n`);

  // Build output sections
  const sections = results.map((r, i) => {
    const statusIcon = r.status === "fulfilled" ? "✓" : "✗";
    return `## Agent ${i + 1}: ${r.agent} [${statusIcon}]\n**Task:** ${r.task}\n\n${r.output}`;
  });

  const scratchpadDump = activeScratchpad.dump();
  const scratchpadSection = scratchpadDump !== "[scratchpad is empty]"
    ? `\n\n---\n\n## Shared Scratchpad\n${scratchpadDump}`
    : "";

  // Synthesis
  let synthesisSection = "";
  if (shouldSynthesize && succeeded >= 2) {
    ui.info("  🧠 Synthesizing swarm results...\n");
    const synthesis = await synthesizeResults(results, options.synthesisPrompt);
    if (synthesis) {
      synthesisSection = `\n\n---\n\n## Synthesis\n${synthesis}`;
    }
  }

  // Cleanup
  activeScratchpad = null;

  return `[SWARM COMPLETE — ${tasks.length} agents, ${succeeded} succeeded, ${failed} failed, ${elapsed}s]

${sections.join("\n\n---\n\n")}${scratchpadSection}${synthesisSection}

[END SWARM OUTPUT — Synthesize findings and continue.]`;
}

// Tool schema for spawn_swarm
export const schema = {
  type: "function",
  function: {
    name: "spawn_swarm",
    description:
      "Launch multiple agents or workflows in parallel. Supports agent IDs and workflow names. Agents share a scratchpad to coordinate and avoid duplicate work. Results are automatically synthesized into a unified summary.",
    parameters: {
      type: "object",
      properties: {
        tasks: {
          type: "array",
          description: "Array of tasks to run in parallel (max 10)",
          items: {
            type: "object",
            properties: {
              agent: {
                type: "string",
                description: "Agent ID or workflow name (e.g. 'youtube', 'researcher')",
              },
              task: {
                type: "string",
                description: "Task description for this agent",
              },
            },
            required: ["agent", "task"],
          },
        },
        synthesize: {
          type: "boolean",
          description: "Run post-swarm synthesis (default: true)",
        },
        synthesisPrompt: {
          type: "string",
          description: "Custom prompt for synthesis step",
        },
      },
      required: ["tasks"],
    },
  },
};

// Tool run function
export async function run({ tasks, synthesize, synthesisPrompt }, { signal }) {
  // Limit to 10 concurrent agents
  const limitedTasks = tasks.slice(0, 10);
  if (tasks.length > 10) {
    ui.info(`  ⚠ Swarm limited to 10 agents (${tasks.length} requested)`);
  }

  return runSwarm(limitedTasks, { synthesize, synthesisPrompt, signal });
}
