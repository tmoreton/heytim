# Bot catalog research

Updated September 12, 2026.

## Decision

Co-launch **Creator Studio** and **Trend Scout** first. They close a real catalog-composition gap and match a strong open-source pattern: people want agents that gather fresh public signals, turn those signals into a content decision, and keep a human in control of creation or publishing.

The next catalog batch is **Morning Brief**, draft-only **Social Writer**, **Meeting Prep**, and **Career Coach**. The first three are featured; Career Coach remains discoverable without crowding general onboarding. Add **Web Operator** only after focused approval, site-policy, and failure-recovery evaluations. Keep Meeting Follow-up and Knowledge Librarian behind their required connector work, and improve the Gmail bot OAuth already creates instead of adding a duplicate Inbox Assistant.

GitHub stars are a rough interest signal, not product demand or a quality score. This review uses public repository descriptions, activity, and star counts captured from the GitHub repository API on September 11, 2026. Counts will change.

## What is popular and relevant

| Pattern | Representative repositories at review time | FroggyBot decision |
| --- | --- | --- |
| Coding agents | [OpenHands](https://github.com/OpenHands/OpenHands) (87,527), [Qwen Code](https://github.com/QwenLM/qwen-code) (27,777), [SWE-agent](https://github.com/SWE-agent/SWE-agent) (20,305) | Large category, but a generic coding persona would be weaker than dedicated coding agents. Revisit a narrowly scoped GitHub Engineer only after repository access, sandboxing, diff review, and write approvals are stable public dependencies. |
| Fresh cross-platform research | [Agent Reach](https://github.com/Panniantong/Agent-Reach) (79,481 stars), [last30days-skill](https://github.com/mvanhorn/last30days-skill) (61,851), [social-media-research-skills](https://github.com/ScrapeCreators/social-media-research-skills) (2,259) | Ship Trend Scout with explicit source windows, corroboration, and no invented growth metrics. |
| Creator and social production | [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) (122,515), [Postiz](https://github.com/gitroomhq/postiz-app) (35,718), [youtube-automation-agent](https://github.com/darkzOGx/youtube-automation-agent) (3,332), [social-media-agent](https://github.com/langchain-ai/social-media-agent) (2,785) | The first two are adjacent evidence for generation and publishing demand; youtube-automation-agent is a closer workflow match. Ship Creator Studio for research, strategy, and thumbnails, but keep publishing and private analytics out of scope and favor human review. |
| Daily intelligence briefings | [daily-briefing](https://github.com/amr05008/daily-briefing), [today](https://github.com/philkomarny/today), [daily-ai-news-brief](https://github.com/richardadonnell/daily-ai-news-brief) | Add Morning Brief as a personalized, source-backed point-in-time workflow. Let the app schedule a run, but do not give the bot nonexistent schedule management, inbox, calendar, or private-feed access. |
| Meeting and career preparation | [CrewAI examples](https://github.com/crewAIInc/crewAI-examples) includes meeting prep, meeting assistance, recruitment, and profile-to-position workflows; [career-companion](https://github.com/mishafyi/career-companion) is a narrower application and interview example. | Ship Meeting Prep now using public professional research and supplied context. Ship Career Coach for truthful file-backed application work, but keep both non-transactional until reviewed account connectors exist. |
| Browser task automation | [browser-use](https://github.com/browser-use/browser-use) (114,257), [Stagehand](https://github.com/browserbase/stagehand) (24,219), [Skyvern](https://github.com/Skyvern-AI/skyvern) (22,975) | Strong next category, but not yet the safest next bot. Web Operator must be excluded from groups and schedules at launch, read/prepare by default, respect site terms, make no CAPTCHA-bypass promise, confirm consequential actions, and prove recovery/resumption before release. |
| Deep research | [STORM](https://github.com/stanford-oval/storm) (31,276), [GPT Researcher](https://github.com/assafelovic/gpt-researcher) (29,414), [Alibaba DeepResearch](https://github.com/Alibaba-NLP/DeepResearch) (19,932) | High demand that FroggyBot already covers with Research & Reports. Improve source quality and evaluation rather than add a duplicate persona. |
| Realtime voice agents | [Pipecat](https://github.com/pipecat-ai/pipecat) (15,441), [LiveKit Agents](https://github.com/livekit/agents) (14,144) | Popular but currently outside FrogBot's bot-tool surface. Do not imply that speech-to-text in the message composer provides a live voice agent or meeting recorder. |
| Meeting follow-up | [Meetily](https://github.com/Zackriya-Solutions/meetily) (30,658) | Add after a reviewed Fathom or Plaud connection can provide the meeting record. Do not imply live transcription from a prompt-only skill. |
| Inbox assistance | [Inbox Zero](https://github.com/elie222/inbox-zero) (12,189) | FrogBot already creates a private Gmail Assistant after OAuth. Improve or skill-enable that bot after Gmail connections have a stable public dependency or connection recipe; do not add a duplicate public template. Sending is currently unavailable and should remain a separately designed, explicitly approved future capability. |
| Personal knowledge and document search | [Khoj](https://github.com/khoj-ai/khoj) (37,277), [Onyx](https://github.com/onyx-dot-app/onyx) (32,030) | Add Knowledge Librarian after Dropbox, Box, Drive, or another indexed document source is reviewed. Preserve source citations and access boundaries. |
| Financial agent teams | [TradingAgents](https://github.com/TauricResearch/TradingAgents) (104,691), [ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) (63,336) | High interest, high consequence. Defer until there is reliable read-only market data, freshness controls, evaluation, and clear non-execution boundaries. |
| General workflow builders | [n8n](https://github.com/n8n-io/n8n) (204,042), [Sim](https://github.com/simstudioai/sim) (29,615) | Do not imitate with a generic persona. Add narrow outcome bots only when their write connectors and approval rules are ready. |

## Recommended sequence

1. **First release: Trend Scout and Creator Studio** — Trend Scout performs point-in-time research across YouTube, recent X posts, and the web, with explicit coverage gaps and independent corroboration before a cross-platform label. Creator Studio adds public YouTube strategy and a generated thumbnail with explicit visual checking and honest draft labeling when copy cannot be verified; its image tool excludes it from group replies and group schedules. Direct turns preflight the full tool set, so research-only requests still need approval unless Image Generator was persistently allowed; that persistent approval also permits direct bot schedules. The YouTube target has no transcripts, playback, private Studio analytics, upload, or publishing.
2. **Everyday outcome batch** — Morning Brief turns fresh public sources into a relevant daily decision aid; Social Writer turns supplied or researched material into platform-specific drafts without publishing; Meeting Prep produces public-source context, questions, agenda, and checklist without calendar or transcript claims; Career Coach uses supplied facts and Files & Data for truthful application and interview artifacts. Keep the first three featured and Career Coach discoverable.
3. **Web Operator** — design a direct-chat browser worker that researches and prepares tasks by default. Release only after explicit consequential-action confirmation, site-terms guidance, CAPTCHA boundaries, and reliable recovery/resumption are tested.
4. **Meeting Follow-up** — summarize an authorized Fathom or Plaud record into decisions, owners, and follow-ups.
5. **Gmail Assistant upgrade** — add triage, follow-up, and shared-list guidance to the private bot that OAuth already creates. Sending remains unavailable; any future send action needs separate approval and evaluation.
6. **Knowledge Librarian** — answer and organize from authorized document sources with citations.

A trading bot and a general autonomous workflow bot are not appropriate catalog additions yet.

## Connector priorities

External Codex plugins are not automatically FrogBot runtime tools. Do not reference vidIQ, Fathom, Plaud, Asana, ClickUp, Trello, Dropbox, Box, or Canva from a public bot until FrogBot has a reviewed stable connector ID, credential flow, and runtime binding for that service.

For later integration work, prioritize vidIQ or direct YouTube owner analytics for creator metrics; one of Fathom or Plaud for authorized meeting records; one project system rather than three overlapping choices; and Dropbox or Box for permission-aware document grounding. Canva is optional for editable design handoff and is not required for current image generation.
