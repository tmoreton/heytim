from __future__ import annotations

FALLBACK_TOOLS = [
    {
        "id": "web",
        "name": "Web reader",
        "description": "Open and summarize a specific web page.",
        "provider": "stan",
        "risk": "read",
        "runtime": {"kind": "stan_builtin", "name": "web_fetch"},
        "enabled": True,
    },
    {
        "id": "web_search",
        "name": "Web search",
        "description": "Search the live web and return relevant sources.",
        "provider": "agentcore-gateway",
        "risk": "read",
        "runtime": {"kind": "gateway", "operations": ["WebSearch"]},
        "enabled": True,
    },
    {
        "id": "calculator",
        "name": "Calculator",
        "description": "Do exact arithmetic safely.",
        "provider": "frogbot",
        "risk": "read",
        "runtime": {"kind": "local", "name": "calculator"},
        "enabled": True,
    },
    {
        "id": "current_time",
        "name": "World clock",
        "description": "Check the current time in any timezone.",
        "provider": "frogbot",
        "risk": "read",
        "runtime": {"kind": "local", "name": "current_time"},
        "enabled": True,
    },
    {
        "id": "x_search",
        "name": "X / Twitter search",
        "description": "Search recent public posts on X.",
        "provider": "agentcore-gateway",
        "risk": "read",
        "credential": "FrogBotXApi",
        "runtime": {"kind": "gateway", "operations": ["x_search_recent"]},
        "enabled": False,
    },
    {
        "id": "youtube_search",
        "name": "YouTube research",
        "description": "Find public videos and inspect metadata and comments.",
        "provider": "agentcore-gateway",
        "risk": "read",
        "credential": "FrogBotYouTubeApi",
        "runtime": {
            "kind": "gateway",
            "operations": [
                "youtube_search",
                "youtube_video_details",
                "youtube_comments",
            ],
        },
        "enabled": False,
    },
    {
        "id": "task_list",
        "name": "Task tracker",
        "description": "Keep a live checklist during longer, multi-step work.",
        "provider": "stan",
        "risk": "sandbox",
        "runtime": {"kind": "stan_plugin", "name": "todos"},
        "enabled": True,
    },
    {
        "id": "delegate",
        "name": "Focused delegate",
        "description": "Hand a focused subtask to a fresh agent and bring back its conclusion.",
        "provider": "stan",
        "risk": "sandbox",
        "runtime": {"kind": "stan_subagent", "name": "generalist"},
        "enabled": True,
    },
    {
        "id": "code_interpreter",
        "name": "Code interpreter",
        "description": "Run Python, JavaScript, or TypeScript in an isolated AgentCore sandbox.",
        "provider": "agentcore",
        "risk": "sandbox",
        "runtime": {"kind": "agentcore", "name": "code_interpreter"},
        "enabled": True,
    },
    {
        "id": "browser",
        "name": "Interactive browser",
        "description": "Open websites, navigate pages, interact with controls, and extract visible information.",
        "provider": "agentcore",
        "risk": "interactive",
        "runtime": {"kind": "agentcore", "name": "browser"},
        "enabled": True,
    },
]

FALLBACK_SKILLS = [
    {
        "id": "planner",
        "version": 1,
        "name": "Planner",
        "description": "Turn goals into practical next steps.",
        "requiredToolIds": [],
        "instructions": """# Planner

Turn an outcome into a short plan that can be acted on immediately.

1. Restate the desired outcome and any hard constraints.
2. Identify the smallest useful milestone.
3. Order the work by dependency and risk.
4. Call out the one decision or missing fact that could materially change the plan.
5. End with the next concrete action.

Prefer five useful steps over a long generic checklist.""",
        "source": "official",
        "visibility": "public",
        "editable": False,
    },
    {
        "id": "researcher",
        "version": 1,
        "name": "Researcher",
        "description": "Investigate questions and synthesize evidence.",
        "requiredToolIds": ["web", "web_search"],
        "instructions": """# Researcher

Research claims before presenting them as fact.

1. Clarify the question, timeframe, and decision it supports.
2. Prefer primary and authoritative sources.
3. Compare more than one source when the claim is consequential or disputed.
4. Separate directly supported facts from inference.
5. Cite the source URL next to the claim it supports.
6. State important uncertainty and what would resolve it.

Do not pad the answer with search process. Lead with the useful conclusion.""",
        "source": "official",
        "visibility": "public",
        "editable": False,
    },
    {
        "id": "writer",
        "version": 1,
        "name": "Writer",
        "description": "Draft polished, audience-aware copy.",
        "requiredToolIds": [],
        "instructions": """# Writer

Produce writing that is ready to use.

1. Preserve the user's facts, intent, and level of certainty.
2. Match the audience and requested channel.
3. Lead with the point and remove throat-clearing.
4. Prefer concrete language and natural sentence rhythm.
5. Return the finished draft before optional notes.

Ask a question only when a missing detail would materially change the result.""",
        "source": "official",
        "visibility": "public",
        "editable": False,
    },
]
