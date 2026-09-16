from __future__ import annotations

BOT_NAME_MAX_LENGTH = 48
BOT_TAGLINE_MAX_LENGTH = 120
BOT_PROMPT_MAX_LENGTH = 12_000
GROUP_NAME_MAX_LENGTH = 64
GROUP_MEMORY_MAX_LENGTH = 4_000
MESSAGE_MAX_LENGTH = 8_000
SCHEDULE_NAME_MAX_LENGTH = 64
SCHEDULE_PROMPT_MAX_LENGTH = 8_000
SKILL_NAME_MAX_LENGTH = 80
SKILL_DESCRIPTION_MAX_LENGTH = 240
SKILL_INSTRUCTIONS_MAX_LENGTH = 20_000
MEMORY_MAX_LENGTH = 16_000
MAX_ATTACHMENTS_PER_MESSAGE = 5
IMAGE_MAX_BYTES = 3_750_000
DOCUMENT_MAX_BYTES = 4_500_000
MAX_PHOTO_DIMENSION = 1_920
SCHEDULE_DAY_OF_MONTH_MIN = 1
SCHEDULE_DAY_OF_MONTH_MAX = 28


def client_constraints() -> dict:
    return {
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
        "imageMaxBytes": IMAGE_MAX_BYTES,
        "documentMaxBytes": DOCUMENT_MAX_BYTES,
        "maxPhotoDimension": MAX_PHOTO_DIMENSION,
    }
