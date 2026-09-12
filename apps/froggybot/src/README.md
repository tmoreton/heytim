# Mobile source map

```text
app/          Expo Router shells; choose which feature to show
features/     Screens and components grouped by user-facing capability
components/   Small visual building blocks shared by features
lib/          Composition adapters, theme values, and the production-disabled preview switch
```

Routes stay thin. Screens receive server-derived permissions and constraints through the packaged client controllers. `lib/api.ts` is the only composition point between
screens and application data. Domain contracts, transport, state reconciliation, platform controllers, native transcription, and preview behavior live in sibling packages. The local preview implementation is selected by Metro only when
`FROGBOT_ENABLE_LOCAL_PREVIEW=1`; normal and production bundles resolve a fail-closed adapter that
does not import the demo engine.

For the guided reading order, see [`docs/tutorial.md`](../../../docs/tutorial.md).
