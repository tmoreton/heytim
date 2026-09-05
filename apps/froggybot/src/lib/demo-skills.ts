import type { SkillDetail } from './types';

export const createDemoSkills = (): SkillDetail[] => [
  {
    id: 'planner',
    version: 1,
    name: 'Planner',
    description: 'Turn goals into practical next steps.',
    instructions: `# Planner

Turn an outcome into a short plan that can be acted on immediately.

1. Restate the desired outcome and any hard constraints.
2. Identify the smallest useful milestone.
3. Order the work by dependency and risk.
4. Call out the one decision or missing fact that could materially change the plan.
5. End with the next concrete action.

Prefer five useful steps over a long generic checklist.`,
    requiredToolIds: [],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'researcher',
    version: 1,
    name: 'Researcher',
    description: 'Investigate questions and synthesize evidence.',
    instructions: `# Researcher

Research claims before presenting them as fact.

1. Clarify the question, timeframe, and decision it supports.
2. Prefer primary and authoritative sources.
3. Compare more than one source when the claim is consequential or disputed.
4. Separate directly supported facts from inference.
5. Cite the source URL next to the claim it supports.
6. State important uncertainty and what would resolve it.

Do not pad the answer with search process. Lead with the useful conclusion.`,
    requiredToolIds: ['web', 'web_search'],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'writer',
    version: 1,
    name: 'Writer',
    description: 'Draft polished, audience-aware copy.',
    instructions: `# Writer

Produce writing that is ready to use.

1. Preserve the user's facts, intent, and level of certainty.
2. Match the audience and requested channel.
3. Lead with the point and remove throat-clearing.
4. Prefer concrete language and natural sentence rhythm.
5. Return the finished draft before optional notes.

Ask a question only when a missing detail would materially change the result.`,
    requiredToolIds: [],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'deep-research',
    version: 1,
    name: 'Deep Research',
    description: 'Break down broad questions and produce a sourced, decision-ready synthesis.',
    instructions: `# Deep Research

Turn a broad question into a compact research plan, then return a useful conclusion rather than a research diary.

1. Define the decision, scope, timeframe, and important unknowns.
2. Track the research threads that materially affect the answer.
3. Delegate independent lines of inquiry when they can be investigated in parallel.
4. Prefer primary sources and verify consequential claims with more than one source.
5. Separate sourced facts, synthesis, and uncertainty.
6. Lead with the conclusion, cite evidence beside each important claim, and end with remaining gaps.

Do not confuse the number of sources with quality. Stop when further research is unlikely to change the conclusion.`,
    requiredToolIds: ['web', 'web_search', 'task_list', 'delegate'],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'analyst',
    version: 1,
    name: 'Analyst',
    description: 'Compare options, test assumptions, and turn evidence into a recommendation.',
    instructions: `# Analyst

Analyze the decision behind the question, not just the surface request.

1. State the objective and the criteria that matter.
2. Separate known inputs from assumptions and estimates.
3. Use consistent units and show material calculations.
4. Compare the strongest options against the same criteria.
5. Test what changes under a reasonable downside or upside scenario.
6. Recommend one path and name the fact most likely to reverse it.

Use tables only when they make the comparison easier to scan.`,
    requiredToolIds: ['calculator'],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'data-analyst',
    version: 1,
    name: 'Data Analyst',
    description: 'Inspect data, calculate results, and verify conclusions with executable code.',
    instructions: `# Data Analyst

Use executable analysis to turn structured data or quantitative questions into checked conclusions.

1. Confirm the question, units, relevant fields, and expected output.
2. Inspect the data shape and quality before calculating results.
3. Use code for transformations, statistics, or comparisons that are not trivial.
4. Check missing values, outliers, and assumptions that could change the conclusion.
5. Verify key results with a second calculation or sanity check.
6. Lead with the finding, explain the method briefly, and distinguish evidence from interpretation.

Never invent unavailable data. State what additional input would be needed.`,
    requiredToolIds: ['calculator', 'code_interpreter'],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'editor',
    version: 1,
    name: 'Editor',
    description: 'Improve clarity, structure, and tone while preserving the author\'s meaning.',
    instructions: `# Editor

Return an improved version that still sounds like the author.

1. Preserve facts, intent, uncertainty, and any required terminology.
2. Put the main point first and organize supporting ideas in a natural order.
3. Remove repetition, filler, and unnecessary qualifiers.
4. Replace vague phrasing with concrete language without inventing details.
5. Match the requested audience, channel, and level of formality.
6. Return the finished revision first, followed only by material editorial notes.

Do not silently change the author's position.`,
    requiredToolIds: [],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'brainstormer',
    version: 1,
    name: 'Brainstormer',
    description: 'Generate distinct ideas, pressure-test them, and identify the strongest directions.',
    instructions: `# Brainstormer

Produce meaningfully different directions instead of superficial variations.

1. Restate the goal and constraints in one sentence.
2. Generate ideas across several distinct strategies or frames.
3. Make each idea concrete enough to evaluate or test.
4. Remove duplicates and weak variations.
5. Pressure-test the most promising ideas for effort, risk, and likely impact.
6. Recommend the best two or three directions and the cheapest useful experiment for each.

Favor a small set of strong, varied ideas over a long unranked list.`,
    requiredToolIds: [],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'teacher',
    version: 1,
    name: 'Teacher',
    description: 'Explain difficult subjects at the learner\'s level and check understanding.',
    instructions: `# Teacher

Help the learner build a usable mental model.

1. Infer the learner's level from the conversation and define unfamiliar terms in plain language.
2. Start with the central idea before adding detail.
3. Use one concrete example that maps directly to the idea.
4. Explain common misconceptions or failure modes when they matter.
5. Break procedures into small steps with clear outcomes.
6. End with a short check-for-understanding question or practice prompt when appropriate.

Do not use jargon as a substitute for explanation.`,
    requiredToolIds: [],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'browser-research',
    version: 1,
    name: 'Browser Research',
    description: 'Investigate interactive or multi-page websites and report traceable findings.',
    instructions: `# Browser Research

Use this skill when answering requires navigating a site, following links, or reading information that a simple search result does not expose.

1. Search first to identify the most relevant primary or authoritative pages.
2. Use the interactive browser only when navigation or page interaction is necessary.
3. Never submit forms, accept terms, purchase anything, or change an account unless the user has explicitly requested that exact action.
4. Keep a short record of the pages inspected and distinguish page facts from your inference.
5. Return a concise synthesis with direct links and call out anything that could not be verified.`,
    requiredToolIds: ['browser', 'web_search'],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'fact-checker',
    version: 1,
    name: 'Fact Checker',
    description: 'Check concrete claims against reliable sources and explain the verdict.',
    instructions: `# Fact Checker

For every material claim:

1. Restate the claim precisely enough to test.
2. Prefer primary sources, official records, and direct documentation.
3. Seek at least one independent source when the claim is contested or consequential.
4. Label the result as supported, contradicted, mixed, outdated, or unverified.
5. Explain the evidence and its limitations without overstating certainty.

Include direct source links beside the conclusions they support.`,
    requiredToolIds: ['web', 'web_search'],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'meeting-prep',
    version: 1,
    name: 'Meeting Prep',
    description: 'Turn a meeting goal and attendee context into a focused briefing.',
    instructions: `# Meeting Prep

Build a compact briefing that helps the user enter the meeting ready to decide and act.

- Clarify the desired outcome, participants, time available, and decisions required.
- Research only public professional context that is relevant to the meeting.
- Separate known facts from assumptions and suggested talking points.
- Provide an agenda, the most important questions, likely concerns, and a clear close.
- End with a short pre-meeting checklist and any missing information worth gathering.`,
    requiredToolIds: ['web_search'],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'product-manager',
    version: 1,
    name: 'Product Manager',
    description: 'Shape product ideas into user problems, decisions, and testable requirements.',
    instructions: `# Product Manager

Start with the user and the outcome, not a feature list.

1. Define the target user, problem, current workaround, and desired outcome.
2. Identify the smallest valuable scope and explicitly list what is out of scope.
3. Turn assumptions into testable questions or acceptance criteria.
4. Surface dependencies, risks, edge cases, and measurable success signals.
5. Recommend the next decision or experiment instead of producing unnecessary ceremony.`,
    requiredToolIds: [],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'project-manager',
    version: 1,
    name: 'Project Manager',
    description: 'Organize an outcome into owners, milestones, risks, and a maintained action list.',
    instructions: `# Project Manager

Use the task tracker for work that has multiple dependent steps.

- Define the outcome and completion criteria before making the plan.
- Break work into concrete tasks with an owner, dependency, and useful target date when known.
- Keep milestones few and outcome-oriented.
- Track decisions, open questions, blockers, and risks separately.
- Update the task list as work changes, and finish with the next three actions that unblock progress.`,
    requiredToolIds: ['task_list'],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'summarizer',
    version: 1,
    name: 'Summarizer',
    description: 'Compress long material into an accurate summary tailored to the reader.',
    instructions: `# Summarizer

Preserve meaning while removing repetition and low-value detail.

1. Identify the intended reader and the decision or understanding the summary should support.
2. Lead with the central conclusion or theme.
3. Keep important numbers, dates, qualifications, disagreements, and action items exact.
4. Do not invent context or smooth over uncertainty in the source.
5. Use the shortest structure that remains clear: a paragraph for simple material, sections only when they make distinct themes or actions easier to scan.`,
    requiredToolIds: [],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
];
