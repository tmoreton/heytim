# Public website

Simple Vite + React site for HeyTim's marketing pages and browsable bot/skills
library. There is deliberately no browser chat, account login, Expo, or native
dependency. The iPhone and Mac apps are maintained together in `../iOS`.

```sh
npm ci
npm run dev
npm run verify
npm run build
npm run preview
```

The homepage introduces HeyTim through memory, shared groups, recurring work,
customizable bots, account connections, and native Apple features. `/features`
contains the full capability guide, including integration permission boundaries.
See `../../docs/website-product-audit-2026-09-26.md` for the source audit and copy decisions.

React owns the example conversation switcher, mobile navigation, library search,
and category filtering. All
public pages are prerendered at build time so direct links and no-JavaScript
visits work. `/app` is an Apple-app handoff, not a chat route. `/invite` preserves
the `kind` and `token` expected by the existing native invitation parser.
The download page links to the latest direct Mac release and the iPhone beta
access request; both require an invited account. Route-specific metadata,
canonical URLs, a sitemap, and robots directives are produced during prerendering.

DM Sans is self-hosted under its bundled SIL Open Font License in
`public/assets/fonts/`. The bot mark and provider images reuse the Apple app's
existing brand assets. The illustrative homepage conversations never call a model
or create real tasks.

The build copies only the public allowlist from `../../catalog`: `catalog.json`,
`skills/`, `bots/`, and `tools/`. The production API reads the catalog at
`https://heytim.ai/catalog.json`.
Never copy `services/API/amplify_outputs.json` or secrets into this site.

The monorepo's Pages workflow builds and publishes `heytim.ai`. The
`../../scripts/deploy-website.sh` command verifies the release and queues that
workflow. Website publishing and Apple TestFlight
releases are independent; a website-only change need not rebuild an app. See
`../../docs/monorepo-migration.md` for hosting history.
