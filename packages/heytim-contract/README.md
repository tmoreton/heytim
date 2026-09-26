# HeyTim contracts

Framework-neutral application DTOs, command interfaces, and generated HTTP routes shared by the backend client and presentation applications.

`src/api-contract.generated.ts`, `openapi.generated.json`, and the Swift route table are generated from the backend route contract. `src/platform-contract.json` is the canonical source for client limits and Apple device capabilities; checked-in Python, TypeScript, and Swift projections are generated from it.

Run `npm run contract:generate` from `services/API` after changing either source contract. CI runs `npm run contract:check` to reject stale projections.
