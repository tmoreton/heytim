import { CHIEF_COLOR } from '@froggybot/client';
import type { Message } from '@froggybot/contracts';

// A representative inline report also exercises wide tables in the app preview.
export const demoTripBrief = `## Weekend plan: five decisions before booking

This is an **illustrative preview**, not live availability or pricing. Keep the trip walkable, include vegetarian food, and confirm the Sunday return before spending anything.

| # | Task | Owner | Effort | Rationale / source |
| --- | --- | --- | --- | --- |
| 1 | Compare Saturday morning train departures and Sunday afternoon returns. | You | 15 min | Use [Amtrak](https://www.amtrak.com/) to confirm the current timetable and leave enough time to be home by 6 PM. |
| 2 | Shortlist two hotels within walking distance of the Old Port. | Jordan | 20 min | Compare the total including taxes and cancellation terms. No room or rate has been verified yet. |
| 3 | Check a vegetarian dinner menu and reservation availability. | Jordan | 10 min | Confirm opening hours and dietary options directly with the restaurant before booking. |
| 4 | Set aside a weather-friendly afternoon option and one outdoor walk. | You | 10 min | Pick an indoor fallback so a rainy day does not require a car or a last-minute change of neighborhood. |
| 5 | Review the combined transport, hotel, food, and contingency budget. | Both | 15 min | Keep the total under **$1,200**. Approve the exact costs together before making any non-refundable purchase. |

### Budget guardrail

| Category | Illustrative limit |
| --- | ---: |
| Transport | $300 |
| Hotel, including taxes | $400 |
| Food | $250 |
| Activities and contingency | $250 |

These are spending limits, not quotes. If transport or the hotel exceeds its limit, revise the plan before booking.

### Next step

Choose the train times first, then share the two hotel options here. I can compare the tradeoffs in the conversation. Nothing has been reserved or purchased. Access to current availability is needed before a final recommendation.`;

export const createDemoTripMessages = (timestamp: string): Message[] => [
  {
    id: 'group-human', role: 'user', authorType: 'user', authorId: 'jordan',
    authorName: 'Jordan', isMine: false,
    text: 'I want somewhere walkable with a genuinely good vegetarian dinner.',
    createdAt: timestamp, status: 'complete',
  },
  {
    id: 'group-bot', role: 'assistant', authorType: 'bot', authorId: 'chief',
    authorName: 'Chief', authorColor: CHIEF_COLOR,
    text: 'Got it. I’ll keep that as a room constraint and ask the team to compare the strongest options.',
    createdAt: timestamp, status: 'complete',
  },
  {
    id: 'group-inline-brief', role: 'assistant', authorType: 'bot', authorId: 'chief',
    authorName: 'Chief', authorColor: CHIEF_COLOR, roundRole: 'synthesizer',
    text: demoTripBrief,
    attachments: [{
      id: 'demo-thumbnail-preview',
      name: 'froggybot-thumbnail-preview.png',
      size: 17_772,
      kind: 'image',
      format: 'png',
      contentType: 'image/png',
      createdAt: timestamp,
    }],
    createdAt: timestamp, status: 'complete',
  },
];
