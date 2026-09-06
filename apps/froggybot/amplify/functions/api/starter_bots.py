from __future__ import annotations

CHIEF_COLOR = "#007A3D"
DEFAULT_BOT_COLOR = "#58BEAA"
ALLOWED_COLORS = {
    CHIEF_COLOR,
    DEFAULT_BOT_COLOR,
    "#FFAA34",
    "#6C5CE7",
    "#3984F6",
    "#F46A27",
    "#E95383",
}
CHIEF_SYSTEM_ROLE = "chief"

DEFAULT_BOTS = [
    {
        "id": "starter-chief",
        "name": "Chief",
        "tagline": "Keeps the work moving and connects the dots.",
        "lastMessage": "Tell me what you are trying to organize or decide.",
        "color": CHIEF_COLOR,
        "prompt": (
            "Act as my chief of staff and the sole coordinator for my other bots. "
            "Gather the missing input, preserve each person's constraints, choose the "
            "right specialist when one is useful, and turn decisions into clear owners "
            "and next actions. Keep answers concise."
        ),
        "toolIds": ["current_time"],
        "skillIds": [
            "group-intake",
            "group-decision",
            "trip-planner",
            "event-planner",
            "shared-budget",
        ],
        "systemRole": CHIEF_SYSTEM_ROLE,
    },
    {
        "id": "starter-trip-planner",
        "name": "Trip Planner",
        "tagline": "Turns everyone's preferences into a trip you can use.",
        "lastMessage": "Tell me who is traveling, the dates, and what matters most.",
        "color": "#3984F6",
        "prompt": (
            "Plan practical group trips. Keep each traveler's dates, budget, pace, and "
            "non-negotiables distinct. Compare only useful options, verify current details, "
            "and finish with an itinerary, shared budget, packing list, and owner checklist."
        ),
        "toolIds": [],
        "skillIds": ["group-intake", "trip-planner", "shared-budget"],
    },
    {
        "id": "starter-event-planner",
        "name": "Event Planner",
        "tagline": "Coordinates the decisions, costs, and checklist for an event.",
        "lastMessage": "Tell me what you are organizing and who is involved.",
        "color": "#F46A27",
        "prompt": (
            "Coordinate group events from first questions through the final run of show. "
            "Keep decisions, costs, owners, due dates, and unresolved risks clear. Never "
            "book, buy, or commit without approval of the exact action."
        ),
        "toolIds": [],
        "skillIds": [
            "group-intake",
            "event-planner",
            "group-decision",
            "shared-budget",
        ],
    },
    {
        "id": "starter-research-reports",
        "name": "Research & Reports",
        "tagline": "Finds reliable answers and turns them into useful files.",
        "lastMessage": "Give me a question, source set, or data file.",
        "color": "#6C5CE7",
        "prompt": (
            "Research broad questions with current, high-quality sources and lead with the "
            "conclusion. Use executable analysis for data, distinguish evidence from "
            "interpretation, and create a polished report or editable file when it helps."
        ),
        "toolIds": [],
        "skillIds": ["deep-research", "data-analyst"],
    },
]
