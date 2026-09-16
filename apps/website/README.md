# Public website

Simple Vite + React site for FroggyBot's marketing pages and browsable bot/skills
library. There is deliberately no browser chat, account login, Expo, or native
dependency. The iPhone and Mac apps are maintained together in `../iOS`.

```sh
npm ci
npm run dev
npm run verify
npm run build
npm run preview
```

`src/pages/` reuses the previous public website's content; `src/styles/` preserves
its visual identity. React owns the library search and category filtering. All
public pages are prerendered at build time so direct links and no-JavaScript
visits work. `/app` is an Apple-app handoff, not a chat route. `/invite` preserves
the `kind` and `token` expected by the existing native invitation parser.

The build copies only the public allowlist from `../../catalog`: `catalog.json`,
`skills/`, `bots/`, and `tools/`. The production API continues reading the same
`https://froggybot.com/catalog.json` and `/skills/.../SKILL.md` URLs. Its legacy
repository identifier stays unchanged to preserve trust and installed versions.
Never copy `services/API/amplify_outputs.json` or secrets into this site.

Deployment: see `../../docs/monorepo-migration.md`. Website publishing and Apple
TestFlight releases are independent; a website-only change need not rebuild an app.
