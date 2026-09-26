"""Generated from packages/heytim-contract/src/platform-contract.json. Do not edit directly."""
from __future__ import annotations

BOT_NAME_MAX_LENGTH = 48
BOT_TAGLINE_MAX_LENGTH = 120
BOT_PROMPT_MAX_LENGTH = 12000
GROUP_NAME_MAX_LENGTH = 64
GROUP_MEMORY_MAX_LENGTH = 4000
MESSAGE_MAX_LENGTH = 8000
SCHEDULE_NAME_MAX_LENGTH = 64
SCHEDULE_PROMPT_MAX_LENGTH = 8000
SCHEDULE_DAY_OF_MONTH_MIN = 1
SCHEDULE_DAY_OF_MONTH_MAX = 28
SKILL_NAME_MAX_LENGTH = 80
SKILL_DESCRIPTION_MAX_LENGTH = 240
SKILL_INSTRUCTIONS_MAX_LENGTH = 20000
MEMORY_MAX_LENGTH = 16000
MAX_ATTACHMENTS_PER_MESSAGE = 5
MAX_TOOLS_PER_BOT = 12
IMAGE_MAX_BYTES = 3750000
DOCUMENT_MAX_BYTES = 4500000
MAX_PHOTO_DIMENSION = 1920

_CLIENT_CONSTRAINTS = {
    "botNameMaxLength": BOT_NAME_MAX_LENGTH,
    "botTaglineMaxLength": BOT_TAGLINE_MAX_LENGTH,
    "botPromptMaxLength": BOT_PROMPT_MAX_LENGTH,
    "groupNameMaxLength": GROUP_NAME_MAX_LENGTH,
    "groupMemoryMaxLength": GROUP_MEMORY_MAX_LENGTH,
    "messageMaxLength": MESSAGE_MAX_LENGTH,
    "scheduleNameMaxLength": SCHEDULE_NAME_MAX_LENGTH,
    "schedulePromptMaxLength": SCHEDULE_PROMPT_MAX_LENGTH,
    "scheduleDayOfMonthMin": SCHEDULE_DAY_OF_MONTH_MIN,
    "scheduleDayOfMonthMax": SCHEDULE_DAY_OF_MONTH_MAX,
    "skillNameMaxLength": SKILL_NAME_MAX_LENGTH,
    "skillDescriptionMaxLength": SKILL_DESCRIPTION_MAX_LENGTH,
    "skillInstructionsMaxLength": SKILL_INSTRUCTIONS_MAX_LENGTH,
    "memoryMaxLength": MEMORY_MAX_LENGTH,
    "maxAttachmentsPerMessage": MAX_ATTACHMENTS_PER_MESSAGE,
    "maxToolsPerBot": MAX_TOOLS_PER_BOT,
    "imageMaxBytes": IMAGE_MAX_BYTES,
    "documentMaxBytes": DOCUMENT_MAX_BYTES,
    "maxPhotoDimension": MAX_PHOTO_DIMENSION,
}


def client_constraints() -> dict:
    return dict(_CLIENT_CONSTRAINTS)
