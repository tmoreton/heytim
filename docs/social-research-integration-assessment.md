# Social research integration assessment

_Decision review: September 20, 2026_

## Recommendation

Run a tightly controlled Apify proof of concept, but do not treat Apify as a universal production answer or launch a
paid add-on yet. Apify is the best fit for quickly testing broad, structured coverage across several networks. Official
platform APIs remain the preferred production route wherever they provide the required public data, because using a
scraping provider does not transfer platform-terms, privacy, or data-use responsibility away from HeyTim.

The user experience can be login-free: HeyTim would own the provider credential and apply product-level allowances.
That removes the end user's connection step; it does not create permission to collect data that a platform prohibits.

## Provider decision by network

| Network | Recommended first route | Apify proof-of-concept candidate | Launch constraint |
| --- | --- | --- | --- |
| YouTube | YouTube Data API with HeyTim's API key | `streamers/youtube-scraper` | Prefer the official API for supported public search, video, channel, and comment data; no end-user login is required for API-key requests. |
| X / Twitter | Official X API if the commercial tier and endpoint coverage are acceptable | `apidojo/tweet-scraper` | X's terms expressly restrict scraping without written permission. Do not ship the scraper route merely because it works technically. |
| Reddit | Reddit commercial Data API agreement | `trudax/reddit-scraper-lite` | Reddit restricts automated collection and commercial Data API use without the applicable agreement. |
| LinkedIn | Approved LinkedIn program or written permission | `harvestapi/linkedin-post-search` and `harvestapi/linkedin-profile-posts` | Highest-risk candidate: LinkedIn's crawling terms prohibit automated crawling without express permission, and general public search is not an open LinkedIn API product. Require explicit legal/product approval before any user pilot. |
| Instagram | Review after the first four | `apify/instagram-api-scraper` | Limit to public content, document the lawful basis, and review Meta terms before enabling. |
| TikTok | Review after the first four | `clockworks/tiktok-scraper` | Treat as a separate policy and reliability review, not automatic scope inherited from the pilot. |

Candidate Actor pricing changes independently of Apify's platform plan. As of this review, the store advertises roughly
$1.50 per 1,000 LinkedIn results, $0.40 per 1,000 X results, $2.40 per 1,000 YouTube results, under $4 per 1,000 Reddit
results, $1.40 per 1,000 Instagram results, and $1.70 per 1,000 TikTok results. Small jobs may also have minimum result,
event, or compute charges, so those figures are useful for screening but not for setting an add-on price.

## Why Apify is the proof-of-concept choice

- It has the widest immediately testable Actor marketplace of the options reviewed, REST APIs, JavaScript and Python
  clients, webhooks, datasets, and per-run controls such as item limits and maximum total charge.
- It can return structured records without asking each HeyTim user to authenticate to each social network.
- It is faster to validate product demand than building and maintaining five anti-bot scraping stacks.
- It is not simply a library dependency. It is an external execution and data-processing platform, and marketplace
  Actors have separate publishers, pricing, schemas, maintenance quality, and privacy implications.

Do not expose Apify's general MCP server or Actor discovery directly to bots. The MCP integration requires an Apify
account/token for execution and can make a very broad Actor catalog available. A product-owned adapter with an explicit
allowlist is a smaller, auditable boundary.

## Production shape if the proof of concept passes

Add one `HeyTimSocialResearch` Lambda target to the existing AgentCore Gateway and keep the Apify token in Secrets
Manager. The Lambda, not the model or Apple client, selects a pinned Actor ID and build for each platform.

The public tool contract should be small:

- `social_search(platform, query, limit, published_after, sort)` for public posts or videos;
- `social_content(url)` for a supported public post, video, or discussion URL;
- an asynchronous job/status path only when a bounded request cannot complete within the normal interactive window.

The adapter must validate every input, cap results, set a per-run dollar ceiling, enforce per-user and global monthly
budgets, normalize output to one stable schema, preserve canonical source URLs, and mark partial results. It should
delete provider datasets and run storage after ingestion, retain only the normalized records needed for the requested
conversation, and record cost, latency, Actor build, item count, and failure class without logging content or tokens.

Use public content only. Exclude email/phone enrichment, bulk profile harvesting, private content, authentication-cookie
inputs, arbitrary Actor IDs, arbitrary proxy settings, and raw dataset access. Prefer Apify-maintained Actors; a
community Actor requires vendor/security review because its creator may be a separate party with access to Actor input
and output and is not automatically covered as an Apify subprocessor.

## Proof-of-concept gate

1. Obtain a legal/product decision for each platform and complete an Apify DPA/vendor review. LinkedIn must be an
   explicit decision, not an assumed part of the pilot.
2. Use a dedicated Apify service account and least-privilege token. Pin exact Actor IDs and builds; disable discovery.
3. Run 25 fixed, representative queries per approved platform with fixed result limits. Measure successful completion,
   relevance, freshness, duplicates, p50/p95 latency, result schema drift, and fully loaded cost per useful search.
4. Compare YouTube and any approved X/Reddit route with their official APIs on the same query set.
5. Add contract fixtures for normalized results, provider timeouts, partial responses, cost-cap failures, malformed
   Actor output, deleted datasets, and platform-level circuit breakers.
6. Proceed only if each enabled platform meets an agreed reliability floor, the legal route is documented, and the
   measured cost supports a product allowance with at least a three-times margin over provider and infrastructure cost.

## Packaging and billing

Start as a Plus-only beta named **Social Research**, with a small monthly allowance and a global provider budget. The
current billing implementation has Free and Plus entitlements but no independent add-on entitlement. Building a true
add-on would require a second Stripe price/subscription item, webhook reconciliation, an entitlement and usage counter,
checkout/portal changes, and Apple/web disclosure updates.

Do not set an add-on price from marketplace list prices. First measure the benchmark above, retries, empty
results, minimum charges, and support burden. If demand and economics hold, introduce a separate allowance after the
pilot instead of silently consuming normal bot-reply credits.

## Alternatives reviewed

- **Bright Data** is the stronger comparison for a managed, high-volume production contract. It advertises a unified
  social scraper portfolio and pay-as-you-go record pricing, but it does not remove target-platform terms risk. Revisit
  it if the pilot proves demand and HeyTim needs stronger schema/SLA/vendor support than community Actors provide.
- **Crawlee** is the best open-source option when self-hosting and source control are more important than speed. It runs
  anywhere, but HeyTim would own proxy operations, blocks, parser drift, retries, storage, and on-call maintenance. It
  is not the economical first choice for a five-network pilot.

## Primary sources

- [Apify integrations and API clients](https://docs.apify.com/integrations/api), [MCP integration](https://docs.apify.com/integrations/mcp), and [pricing](https://apify.com/pricing)
- Candidate Actors: [LinkedIn posts](https://apify.com/harvestapi/linkedin-post-search), [X posts](https://apify.com/apidojo/tweet-scraper), [YouTube](https://apify.com/streamers/youtube-scraper), [Reddit](https://apify.com/trudax/reddit-scraper-lite), [Instagram](https://apify.com/apify/instagram-api-scraper), and [TikTok](https://apify.com/clockworks/tiktok-scraper)
- [Apify security](https://docs.apify.com/security), [shared responsibility](https://docs.apify.com/security/shared-responsibility), [Actor terms](https://docs.apify.com/legal/actor-terms-and-conditions), and [DPA](https://docs.apify.com/legal/data-processing-addendum)
- [Apify dataset retention](https://docs.apify.com/storage/dataset) and [Python Actor client controls](https://docs.apify.com/api/client/python/reference/class/ActorClient)
- [LinkedIn crawling terms](https://www.linkedin.com/legal/crawling-terms) and [API access](https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access)
- [X terms of service](https://x.com/en/tos), [YouTube terms](https://uk.youtube.com/t/terms), and [YouTube Data API search](https://developers.google.com/youtube/v3/docs/search/list)
- [Reddit user agreement](https://redditinc.com/policies/user-agreement) and [Data API terms](https://redditinc.com/policies/data-api-terms)
- [Bright Data Web Scraper API pricing](https://brightdata.com/pricing/web-scraper) and [Crawlee](https://github.com/apify/crawlee)
