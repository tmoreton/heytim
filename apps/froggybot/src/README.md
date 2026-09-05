# Mobile source map

```text
app/          Expo Router shells; choose which feature to show
features/     Product workflows grouped by user-facing capability
components/   Small visual building blocks shared by features
lib/          Cloud adapters, shared types, notifications, and preview data
```

Routes stay thin. A feature owns its state and workflow. `lib/api.ts` is the only interface between
screens and application data, whether the app is using local preview data or AWS.

For the guided reading order, see [`docs/tutorial.md`](../../../docs/tutorial.md).
