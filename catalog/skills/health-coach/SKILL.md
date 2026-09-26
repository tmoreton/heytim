---
name: health-coach
description: Analyze explicitly authorized Apple Health activity and running summaries without exposing raw sensor or route data.
---

# Apple Health Coach

Use this workflow when the user asks about their own recent activity, workouts, steps, or running trends and Apple Health is available to this bot.

1. Establish the user’s goal and timeframe. Ask only for context that would materially change the interpretation, such as current training phase, recent time off, or a stated limitation.
2. Call the narrowest Apple Health operation that answers the question. Prefer daily or period aggregates. Do not request data outside the user’s stated timeframe merely because it is available.
3. Treat missing or partial results as missing coverage, not as zero activity or proof that permission was denied.
4. Separate recorded values from interpretation. Compare like-for-like periods and make units and date boundaries explicit.
5. Return a compact summary, the most useful trend or change, relevant uncertainty, and one or two practical next questions or actions.

This skill is for personal activity reflection, not diagnosis or treatment. Never claim continuous monitoring. Do not request or infer routes, clinical records, medications, reproductive data, sleep details, raw heart-rate samples, protected traits, or unrelated health information. If the user reports symptoms, injury, or an urgent concern, encourage appropriate professional care instead of deriving medical advice from activity data.
