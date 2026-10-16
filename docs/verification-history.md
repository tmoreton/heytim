# HeyTim verification history

Names in dated entries are preserved exactly as they existed when the evidence
was recorded, including legacy repository, cloud-resource, secret, and bundle IDs.

This file records dated checks against deployed environments. It is evidence from a point in time, not a statement that
the current checkout or environment still has the same status.

## 2026-10-16 — bounded Chief routing repeat passed; earlier timeout remains unexplained

- PR [147](https://github.com/tmoreton/heytim/pull/147) merged at **02:45:02 UTC** as
  `1a2f2c226da3e3e61794f82472abc612e47bab36`, after review and passing applicable checks: JavaScript/TypeScript
  and Python CodeQL, change classification, dependency audit, application-backend verification, GitGuardian,
  and the aggregate CodeQL check. Website/catalog, AgentCore runtime, and AgentCore configuration suites were
  skipped as unaffected. The change adds bounded, sanitized read-only routing diagnostics and scopes to the
  existing production-smoke workflow; it does not redeploy or modify the running backend.
- The existing read-only diagnostic [run 38842026243](https://github.com/tmoreton/heytim/actions/runs/38842026243)
  succeeded on that exact merge source, running from **02:45:12–02:45:37 UTC**. Its **10 diagnostic tests passed**
  with zero failures, cancellations, skips, or TODOs. The fixed diagnostic result at **02:45:31.7475330 UTC** was:
  `diagnosticsCompleted: true`, `syntheticRouteFound: true`, `assistantStatus: complete`,
  `configurationChanged: false`, `routeToolActivityObserved: false`, `listBotOptionsActivityObserved: false`,
  `assistantTextClassification: none_recognized`, `targetListed: false`, `targetDeleted: false`,
  `targetHandoffState: target_not_listed`, `targetHandoffCount: 0`, `targetMatchingTaskCount: 0`, and
  `targetHandoffAssistantStatus: missing`.
- These results establish that the latest synthetic routing turn's assistant completed and the target was
  absent from that later listing after smoke cleanup. They do not establish deletion, explain the routing
  failure, or prove that the routing/list-options tools were absent or unused. Activity may contain narration
  instead of exact tool labels; unrecognized assistant text is not proof of successful routing. The zero
  handoff counts were not measured from the absent target's messages.
- Under the owner's deployment/test authorization, the coordinator dispatched **one** bounded Chief-only repeat,
  [run 38842175113](https://github.com/tmoreton/heytim/actions/runs/38842175113), from the same exact source.
  It was created **02:46:50 UTC**, and the Chief defaults/create/edit/routing step began **02:47:17 UTC**.
  The unrelated authenticated workflow/webhook step was skipped. The repeat uses a fresh temporary fixture
  through the existing scoped smoke harness, without redeployment or IAM changes.
- The single repeat completed **SUCCESS at 02:49:07 UTC**. Its fixed Chief summary at
  **02:49:02.0587243 UTC** was `passed: true`,
  `completed: [chief_defaults, credit_preflight, chief_create, chief_edit, chief_routing]`,
  `cleanupSucceeded: true`, `chiefTurns: 3`, and `routedTurnsVerified: 1`. The strict smoke verifies defaults,
  actual created/edited bot state, exactly one target user turn with `source: bot_route` and the supplied task,
  a completed corresponding child turn with the exact required marker reply, and no duplicate routed turn.
  Scoped cleanup of its created temporary fixture succeeded; it does not delete Chief or the fixture account.
- The repeat used unchanged routing runtime, saved Chief model/system-prompt settings, and permissions; PR 147 added diagnostics and
  workflow scope selection, not a routing implementation fix. The earlier timeout remains unexplained and
  did not reproduce in this one bounded recheck. This supports an intermittent observed failure, not a
  demonstrated cause or definitive routing repair. No further paid calls or redeployment were performed after that repeat.
- The repeat's successful sanitized preceding-hour diagnostic step listed one aggregate provider
  `AuthenticationError` at `_base_client.py:request:1777`. That window includes pre-restoration time; the
  summary does not attribute the marker to this successful repeat or establish its event time/cause.
  The fixed Chief pass and verified child reply are separate evidence.
- The prior provider restoration, independent native TextEdit proof, and failed routing checkpoint remain
  preserved in the following dated entry. Live Terminal execution remains blocked and unverified; no
  Terminal command ran and the CUA block was not bypassed.

## 2026-10-16 — OpenRouter restored and native edit proved; final Chief routing gate failed

- After two owner Chief turns ended before native action with the OpenRouter authentication-unavailable
  message, existing [production smoke 38837125623](https://github.com/tmoreton/heytim/actions/runs/38837125623)
  failed without redeployment. Its sanitized preceding-hour summary contained one provider
  `AuthenticationError` at `_base_client.py:request:1777` and one provider `EventLoopException` at
  `event_loop.py:event_loop_cycle:410`. The pinned SDK maps `AuthenticationError` to HTTP 401. This is
  aggregate evidence of provider authentication rejection, not per-owner-turn attribution or proof of the
  rejection's specific cause. Earlier installed-app validation and failure records remain intact.
- The owner explicitly approved replacing HeyTim's deployed OpenRouter key and supplied it on the clipboard.
  The coordinator validated the supplied key using **GET `/api/v1/key`: HTTP 200** and transferred it through
  GitHub CLI standard input to the existing protected production environment secret
  `AGENTCORE_CREDENTIAL_FROGBOT_OPENROUTER`, whose updated-at metadata became
  **2026-10-16 02:01:04 UTC**. During the canonical Mac clipboard-to-GitHub transfer, no key value was printed
  or placed in a local disk file. The existing CI workflow separately creates its owner-only plaintext
  `.env.local` temporarily on the ephemeral runner and removes it on step exit. No key-limit or IAM changes
  were made. The HTTP 200 establishes acceptance of the supplied key by the provider; the later native smoke
  establishes restoration of completion through HeyTim. Credential-setup log evidence and its scope are
  recorded below.
- The coordinator dispatched the existing backend-only
  [production deployment 38838245820](https://github.com/tmoreton/heytim/actions/runs/38838245820) from exact
  main source `71a595bf86ec5f3ad8ca38061af0e7b2b80426d2`. The coordinator confirmed the diff from previously
  deployed backend source `8fd15dc27c585bcaa9fda0cf47f2a77179286e76` contains native app/tests and documentation
  changes, with runtime, API, and infrastructure code unchanged. Draft preflight passed and the Ubuntu
  deployment job began **02:01:31 UTC**. Apple publication is excluded by this scope.
- The workflow's pinned AgentCore CLI **0.29.0** reads the protected secret as
  `AGENTCORE_CREDENTIAL_HEYTIM_OPENROUTER` from an owner-only temporary `agentcore/.env.local`, deleted on step
  exit. Source inspection confirms that an existing `HeyTim_OpenRouter` API-key provider is updated in place
  through `UpdateApiKeyCredentialProvider`, then read back for its provider ARN. The established deployment
  path also reconciles the existing X/YouTube API-key providers and runs the normal server verification,
  dependency audit, AgentCore/Amplify deployment, resource validation, managed evaluation, and authenticated
  workflow/webhook/Chief checks. The AgentCore deployment and deployed-resource resolution steps passed;
  Amplify deployment began **02:07:15 UTC** and passed. The resource-validation step began
  **02:09:36 UTC**. Completed job logs show aggregate `Creating credentials...` from
  **02:06:35.2001432 UTC** through success at **02:06:36.3138614 UTC**. The pinned noninteractive CLI emits
  this aggregate setup status, not the per-provider `Updated API key provider` message emitted by its
  interactive UI. Source inspection plus successful aggregate setup supports in-place reconciliation;
  there is no directly logged provider-specific update timestamp or independently compared key material.
- The installed **Mac 1.1.4 / 20261016004703** settings showed **Connected**, Computer use **Ready**, and
  Accessibility **Granted** after the coordinator resumed the paused session. Existing grants remained
  unchanged. These indicators do not establish successful native observation or editing.
- After the successful AgentCore deployment, the coordinator ran a fresh Chief smoke in the installed 1.1.4 app.
  Chief's returned final report listed **three native calls**: observe TextEdit, type the requested fixture text,
  and observe TextEdit again. That report listed the initial `Untitled` revision
  `2687af6c-cb1b-49c4-944c-fbc8fa469f1e`, target `control_2` / `AXTextArea`, and exact READY seed; it reported
  `actionPerformed: typed`, `verifiedAfterAction: true`, and fresh observation revision
  `38a4f436-bc6f-4f83-9475-8b60ae80b84e` with the OK marker. These counts, revisions, and action flags were read
  from the assistant report, not independently inspected inner tool payloads. Independently, CUA TextEdit
  accessibility readback proved the fixture changed from READY to exactly `HEYTIM_DESKTOP_20261015172350_OK`
  after the chain, with no other local input during it. This establishes an actual edit and readback beyond
  Chief's completion claim. Separately, the UI showed one background progress group; that label was not used
  to count native calls. Chief did not use Terminal, save, or close the fixture.
- The coordinator then closed only the owned fixture through the normal UI. When TextEdit offered Save/Delete,
  the coordinator did not click Delete; it saved the test result to
  `/private/tmp/heytim-desktop-smoke-20261016-cvz0o1ws/HeyTim-desktop-smoke-20261016.rtf` and completed the close.
  CUA subsequently reported no TextEdit window. An independent filesystem check confirmed the file contains
  the exact OK marker with READY absent, owner UID 501, directory mode 0700, and file mode 0600. Chief itself
  performed no save or close. Fresh HeyTim settings around **02:12 UTC** confirmed version/build unchanged,
  Computer use Ready, Accessibility Granted, Connected, and both global Mac app actions and Terminal On;
  no resume action was needed after cleanup.
- Deployment resource validation passed; the managed regression gate began **02:11:09 UTC**.
- Managed evaluation completed successfully with **5/5 sessions**, zero invocation/session/evaluator failures,
  and mean **1.0** for both `Builtin.GoalSuccessRate` and `Builtin.ResponseRelevance` (five evaluated each).
  Artifact **12020640933**, `heytim-agentcore-evaluation-71a595bf86ec5f3ad8ca38061af0e7b2b80426d2`, was
  preserved at **02:16:01 UTC** and expires **2026-11-15 02:16:01 UTC**. Its result JSON was independently
  read in memory and only scalar evaluation counts/scores were emitted. Authenticated production workflow
  verification began **02:16:02 UTC**.
- Server verification passed: **518 runtime tests**, **718 API tests**, **2 evaluator tests**, **10 CDK tests**,
  and **38 Node tests** across the script suites. Dependency audit emitted zero-vulnerability results.
  The authenticated workflow passed bootstrap, attachment read, schedule lifecycle, share revocation,
  approval deny/allow/cancel, and temporary-bot cleanup. The webhook check passed all four fixed stages,
  reported three model turns, and confirmed `cleanupSucceeded: true`.
- The final Chief gate began **02:19:17 UTC**. Its fixed result was `passed: false`, `code: routing_timeout`,
  `completed: [chief_defaults, credit_preflight, chief_create, chief_edit]`, `chiefTurns: 3`,
  `routedTurnsVerified: 0`, and `cleanupSucceeded: true`. The completed create/edit stages verify actual bot
  state through the API. Source inspection shows `routing_timeout` means the 240-second poll did not observe
  a target user turn with `source: bot_route` after the third Chief turn completed. It is distinct from waiting
  for a routed child reply and does not establish whether Chief invoked the routing tool or why no target turn
  was observed. Scoped smoke cleanup succeeded.
- The overall production run ended **FAILURE at 02:24:38 UTC** on that final Chief gate. AgentCore/Amplify
  deployment and resource validation had already passed; the workflow does not automatically roll them back.
  No retry, rollback, or additional mutation was performed during diagnosis. The managed-evaluation artifact
  above remains retained; no production-client-configuration artifact was created after the failed gate.
  This deployment workflow does not include the standalone smoke's sanitized runtime-failure-summary step,
  so no new such summary is available from this run. Routing diagnosis and any further action remain pending.
- Native TextEdit editing and provider completion restoration are proved at this checkpoint; the release gate
  is not fully passing. Live Terminal execution remains unverified: the hard CUA block was not bypassed and
  no Terminal command ran.

## 2026-10-15 — private Mac 1.1.4 installed; live smoke blocked by provider authentication

- After the owner confirmed normal unlock, a normal CUA quit followed by the guarded installer replaced
  **1.1.3 / 20261015233310** with **1.1.4 / 20261016004703** at `/Applications/HeyTim.app`. No AX query followed
  the quit. The release receipt identifies source `34394373dc217c5c03a9768c30d4a4bb12211c1c` from
  [private run 38831274703](https://github.com/tmoreton/heytim/actions/runs/38831274703).
  Rollback is retained at
  `/Users/homelab/Library/Application Support/HeyTim/Rollbacks/1.1.3-20261015233310-before-20261016004703/HeyTim.app`.
- Independent installed-app validation passed **67/67 Mach-O signatures** and all checks, including exact
  version/build, signing team/bundle identity, receipt source, generated production resource, staple,
  Gatekeeper, and Apple Events entitlement. Evidence is
  `/tmp/heytim-native-installed-validation-20261016004703.json`. The DMG was hash-verified during staging;
  it was not rehashed after installation. `Info.plist` has no embedded source commit; the unsigned receipt
  and CI checkout provide source/hash consistency, not independent binary-source proof.
- The installed UI confirmed **1.1.4 / 20261016004703**, **Connected**, **Ready**, Accessibility **Granted**,
  global Mac app actions and Terminal **On**, with the existing owner login retained.
- Two owner Chief turns, around **2026-10-16 01:31 UTC** and **01:39 UTC**, ended with
  `OpenRouter authentication is unavailable. No completion was recorded; please try again after the service connection is restored.`
  Both ended before native action. Independent CUA readback confirmed the disposable TextEdit fixture
  retained its exact seed; it remains open for a later bounded retry. The installed app remained Connected
  with the owner login and native grants intact. The same saved DeepSeek / High configuration had completed
  a turn around **00:12 UTC**.
  Backend source `8fd15dc27c585bcaa9fda0cf47f2a77179286e76` remained deployed unchanged.
- The existing authenticated [production smoke 38837125623](https://github.com/tmoreton/heytim/actions/runs/38837125623)
  failed without redeployment: the synthetic workflow reported `passed: false`, and its Chief stage was skipped.
  Its successful sanitized CloudWatch summary for the preceding hour contained exactly:
  `provider / AuthenticationError / _base_client.py:request:1777 / count 1` and
  `provider / EventLoopException / event_loop.py:event_loop_cycle:410 / count 1`.
  The pinned OpenAI SDK maps `AuthenticationError` to HTTP **401**; the Strands event-loop location wraps
  an underlying exception. This supports a direct provider authentication rejection within that aggregate
  window, rather than a demonstrated AgentCore credential-lookup failure. The summary does not attribute
  either marker to an individual owner turn or prove the reason the provider rejected authentication.
- Read-only metadata showed the runtime Ready at version 12, last updated **2026-10-15 20:07:05 UTC**,
  referencing the existing `HeyTim_OpenRouter` provider. That provider was created and last updated
  **2026-09-26 11:10:55 UTC**. Its service-owned secret metadata reported AWSCURRENT created
  **2026-10-15 20:05:23.885 UTC**, with last change **20:05:23.890 UTC**; both precede the known successful
  00:12 UTC turn. No deletion or rotation date was set. Metadata cannot establish provider-side key validity
  or revocation. No secret values were retrieved, and no stored provider credential, key limit, IAM policy,
  or infrastructure was changed during this diagnosis. The owner's existing OpenRouter tab showed a masked
  key-creation modal; no key value was read or copied and no replacement was performed. Owner authorization
  for replacement remains pending.
- **PENDING — real native smoke:** no successful Chief TextEdit observation/edit/readback has been
  established on 1.1.4. Installation, permission indicators, automated tests, and these provider failures do
  not establish successful editing. Live Terminal execution also remains unverified: the CUA block was
  not bypassed and no Terminal command ran.

## 2026-10-15 — native diagnostics, process identity, and private Mac candidates

- [PR #141](https://github.com/tmoreton/heytim/pull/141) merged as
  `78247cc13dc2475a645d30108af071549bca1ea2`. Its product code matches tested source
  `21d09fd8b1563ea63c8f650ad58b5cbf473ce9a6`; the intervening difference is earlier verification-history
  documentation. The patch changes Mac-native diagnostics, permission handling, and injected regressions.
- [Apple CI 38805258705, attempt four](https://github.com/tmoreton/heytim/actions/runs/38805258705/attempts/4)
  passed **177/177 tests: 144 Mac unit, seven Mac UI, and 26 iPhone UI**, with zero failures, skips, or expected
  failures. [Artifact 12009888690](https://github.com/tmoreton/heytim/actions/runs/38805258705/artifacts/12009888690)
  retains the results. The owner completed the normal authentication required for Xcode setup and Automation Mode;
  the authentication requirement remained enabled. This successful follow-up does not replace the earlier
  point-in-time runner-failure entries.
- Production backend source remains `8fd15dc27c585bcaa9fda0cf47f2a77179286e76`, deployed by successful
  [rollout 38798257566](https://github.com/tmoreton/heytim/actions/runs/38798257566). Runtime, API, AgentCore,
  catalog, and contract files are unchanged by this native patch.
- [Private Mac candidate 38815676122](https://github.com/tmoreton/heytim/actions/runs/38815676122) succeeded from
  source `78247cc13dc2475a645d30108af071549bca1ea2` and produced **1.1.2 / 20261015221541**. Its own shared gate
  passed the same **177/177 tests**, with zero failures/skips/expected failures; the captured summary is
  `/tmp/heytim-mac-candidate-38815676122-native-summary.json`.
  [Receipt artifact 12011453879](https://github.com/tmoreton/heytim/actions/runs/38815676122/artifacts/12011453879)
  retains the candidate evidence. The DMG SHA-256 is
  `11bf33477ac24256caeb93178d4e8ecd86dc102553597c6119a0edf6a2e40d2e`.
- Independent staged and installed validators passed all **67 Mach-O signatures**, app signature, Gatekeeper,
  staple, production configuration, and Apple Events entitlement checks, with no invalid symlinks. Results are
  `/tmp/heytim-native-stage-validation-20261015221541.json` and
  `/tmp/heytim-native-installed-validation-20261015221541.json`.
  At that checkpoint, `/Applications/HeyTim.app` showed **1.1.2**, **Connected**, computer use **Ready**, and
  Accessibility **Granted**, with the owner session retained. The previous 1.1.1 installation was retained for rollback.
- **FAILED — real TextEdit smoke on 1.1.2:** both the initial/background observation and a focused retry failed
  at `AXFocusedWindow` with AX error `-25202`. Neither produced a snapshot or edited the disposable unsaved fixture;
  independent CUA observation still read its exact seed text. Read-only process diagnostics reported TextEdit PID
  `-1` through all inspected AppKit APIs despite live PID `48568`; Terminal metadata reported positive PID `523`.
  The installed adapter's chosen PID was not logged, so this discrepancy is consistent with a process-identity
  cause but does not prove it occurred in the installed process.
- Process-identity follow-up [PR #143](https://github.com/tmoreton/heytim/pull/143) merged as
  `b4bff30151c78f379d37ab4c59b03581617c7209`, whose complete Git tree matches tested source
  `3328d22637ab9d9509be8efb6921439cbbd06db1`. Nine focused XCTest regressions passed and are retained at
  `/tmp/HeyTimNativeProcessUnit-20261015.xcresult`. Both-platform build verification and architecture checks passed.
  Independent review found no blocker within the selection-time scope: owner, canonical executable path, and
  start-time metadata are rechecked during selection; the patch does not claim process epoch binding across
  an existing snapshot's lifetime. The actual compiled metadata resolver proved TextEdit `-1 → 48568` and
  Terminal `523 → 523`, without AX queries, AppleEvents, or UI actions.
- [Shared Apple CI 38821974879](https://github.com/tmoreton/heytim/actions/runs/38821974879) passed
  **186/186 tests: 153 Mac unit, seven Mac UI, and 26 iPhone UI**, with zero failures/skips/expected failures.
  [Artifact 12014250980](https://github.com/tmoreton/heytim/actions/runs/38821974879/artifacts/12014250980)
  retains the results; the scalar summary is `/tmp/heytim-ci-38821974879/native-summary.json`.
- [Private Mac 1.1.3 candidate 38824067697](https://github.com/tmoreton/heytim/actions/runs/38824067697), build
  **20261015233310**, succeeded after its own **186/186 tests**. App notarization was **Accepted** at
  **2026-10-16 00:01:44 UTC** and DMG notarization at **00:08:45 UTC**.
  [Receipt artifact 12015557933](https://github.com/tmoreton/heytim/actions/runs/38824067697/artifacts/12015557933)
  retains the release evidence. The retained DMG is **886,492,478 bytes**, SHA-256
  `7fe9dcc0d6d66ceba284bf9516a86190863a5ce6f9ba50c977e444d9a0c968fe`.
  Independent receipt/source, production destination/API/user-pool, size/hash, and private storage checks passed
  (owner UID `501`, directories `0700`, files `0600`). Unretained ZIP and appcast hashes were not independently
  verified. Independent staged and installed validators subsequently passed all **67 Mach-O signatures**,
  exact version/build, production resource, staple, Gatekeeper, and Apple Events entitlement checks. The previous
  **1.1.2** installation was retained for rollback. The installed UI confirmed **1.1.3 / 20261015233310**,
  **Connected**, **Ready**, Accessibility **Granted**, global Mac app actions and Terminal **On**, with the owner
  login preserved. These installation and permission results do not establish successful native editing.
- **FAILED — real TextEdit smoke on 1.1.3:** native observation returned
  `AXDescription -25200 [pid=48568]`. The correct TextEdit PID is now proved in the installed adapter, but no
  snapshot or edit occurred; independent CUA observation confirmed the fixture seed was unchanged.
- Optional-label follow-up [PR #144](https://github.com/tmoreton/heytim/pull/144) merged as
  `34394373dc217c5c03a9768c30d4a4bb12211c1c`, whose complete Git tree matches reviewed source
  `06f59183beb8a8798ede8b0629ce2f99f58d0847`. It tolerates generic `.failure` only for optional cosmetic control
  labels. Window, role, tree, safety, and value reads remain strict. Button actions and scrolling are withheld
  when their labels are incompletely read; the fallback for known-absent scroll labels is preserved. Six new
  injected cases accompany the existing capture regressions; all **12 focused tests passed**, with zero
  failures/skips/expected failures.
  Both-platform builds, architecture checks, and independent review passed.
- [Shared Apple CI 38829516158](https://github.com/tmoreton/heytim/actions/runs/38829516158) passed
  **192/192 tests: 159 Mac unit, seven Mac UI, and 26 iPhone UI**, with zero failures/skips/expected failures.
  [Artifact 12016948645](https://github.com/tmoreton/heytim/actions/runs/38829516158/artifacts/12016948645)
  expires **2026-10-19 00:44:28 UTC**; the scalar summary is
  `/tmp/heytim-ci-38829516158/native-summary.json`. All applicable PR security/classifier checks passed;
  unchanged service suites were correctly skipped.
- [Private Mac 1.1.4 candidate 38831274703](https://github.com/tmoreton/heytim/actions/runs/38831274703) succeeded
  from source `34394373dc217c5c03a9768c30d4a4bb12211c1c`, build **20261016004703**, with its own **192/192 tests:
  159 Mac unit, seven Mac UI, and 26 iPhone UI**, zero failures/skips/expected failures. The scalar summary was
  captured before cleanup at `/tmp/heytim-mac-candidate-38831274703-native-summary.json`. Duplicate main Apple run
  [38831264897](https://github.com/tmoreton/heytim/actions/runs/38831264897) completed as **Cancelled**.
  On **2026-10-16 UTC**, app ZIP notarization upload completed at **01:09:37**, with **Accepted** at **01:13:07**;
  DMG upload completed at **01:16:16**, with **Accepted** at **01:19:45**.
  [Receipt artifact 12018234832](https://github.com/tmoreton/heytim/actions/runs/38831274703/artifacts/12018234832)
  retains the release evidence. The retained DMG is **891,200,911 bytes**, SHA-256
  `44208bae63971e9b135f8327688cb6f820480c939275a9390d40c1ede0e09b76`.
  Independent receipt/source, production destination/API/user-pool, ownership, and stable size/hash checks passed.
  Unretained ZIP and appcast hashes were not independently verified.
- Independent **staged-app** validation passed **67/67 Mach-O signatures** and every signature, resource, staple,
  Gatekeeper, and entitlement check; results are `/tmp/heytim-native-stage-validation-20261016004703.json`.
  **NOT INSTALLED:** CUA reported the Mac locked and automatic unlock failed. The owner was asked to unlock normally
  through local access or Screen Sharing. No further UI retry, bypass, CLI quit, or installation was attempted.
  The active installed app remains **1.1.3**; the validated 1.1.4 stage is retained for later installation.
  **TODO:** complete owner unlock, guarded installation and independent installed-app validation, then real
  TextEdit observation/edit/readback. Native editing on 1.1.4 remains **PENDING**.
- The approved existing HeyTim → Terminal Automation switch was toggled **On** through normal System Settings
  at **23:53 UTC**. TCC verification at **23:53:23.129 UTC** confirmed team `GVXC5FQ2RP` for
  `/Applications/HeyTim.app`. Read-only System Settings observation at **2026-10-16 01:06:45 UTC** confirmed
  HeyTim → Terminal remained **On** after the 1.1.3 update. These permission checkpoints do not establish
  successful Terminal execution; no Terminal UI or control was used.
- **Artifact provenance limitation:** `Info.plist` does not embed the source commit. The unsigned receipt records
  source/hash consistency alongside CI checkout provenance; it is not independent proof that the binary was built
  from that source.
- **LIMITATION — live Terminal execution:** direct computer-use control of Terminal was blocked by CUA safety.
  The block was not bypassed, and no Terminal command was submitted. Live Terminal execution remains unverified.

## 2026-10-15 — live native-tool dispatch follow-up

- The owner approved Chief's persistent Mac Terminal and Accessibility grants. The installed signed Mac app
  remained connected with its existing owner login, Chief prompt/model, 12 tools, and 17 skills preserved.
- The first live request exposed an SDK invocation mismatch: the model-visible flat device-tool schema did not
  match Strands' inferred required `arguments` parameter. [PR #139](https://github.com/tmoreton/heytim/pull/139),
  merged as `8fd15dc27c585bcaa9fda0cf47f2a77179286e76`, validates the original flat input against the public closed
  JSON schema before interruption. Twenty-five SDK-path regressions cover all eight native operations and invalid
  input. Runtime `jsonschema` uses the already-locked version.
- [Backend rollout 38798257566](https://github.com/tmoreton/heytim/actions/runs/38798257566) succeeded from that
  exact merge: runtime 518, API 718, evaluator two, CDK ten, and Node 38 checks passed. Production resource
  validation, authenticated workflow, webhook smoke, and Chief create/edit/routing smoke passed with cleanup.
  All five managed sessions completed without failures; both GoalSuccessRate and ResponseRelevance averaged
  1.0 over five evaluations. Artifact `12004291355` retains managed regression evidence. The SDK validation
  failure no longer occurred in fresh installed-app turns; requests reached the native Mac adapter.
- Native follow-up [PR #141](https://github.com/tmoreton/heytim/pull/141), source
  `21d09fd8b1563ea63c8f650ad58b5cbf473ce9a6`, requires an actual accessible AX window, preserves safe read errors,
  and clears stale captures. Terminal checks/requests normal macOS consent off-main before list/read, never prompts
  anywhere in execute, and cancels pending reads on grant revocation/sign-out. Delayed results cannot be shared after
  revoke/re-enable. Errors retain only trusted stage/code/PID diagnostics and preserve ambiguous submission status.
  Sixteen new injected regressions accompany existing compile-only AppleScript checks. Final-source
  `./scripts/apple-app.sh build` passed for both iPhone and Mac; architecture/source-size/diff checks and independent
  review passed. This PR remains unmerged; the installed Mac remains **1.1.1 / 20261015172350** while its shared
  Apple gate is blocked. No new private candidate was built or installed from this follow-up.
- [Apple CI 38805258705](https://github.com/tmoreton/heytim/actions/runs/38805258705), attempts one and three,
  each passed all **144 Mac unit tests, zero failures/skips/expected failures**. Both then failed before any Mac UI
  case ran: XCTest runner initialization timed out enabling Automation Mode (XCTFuture code 1000, xcodebuild 65).
  The runner-initialization entry is not an executed UI test case. Neither attempt reached iPhone verification.
  Artifacts `12006182656` and `12005974104` retain the separate failures; local copies are under
  `/tmp/heytim-ci-38805258705` and `/tmp/heytim-ci-38805258705-attempt3`.
- An idle user-owned `testmanagerd` sample showed a synchronous LocalAuthentication/XPC wait in
  `XAMEnableAutomationMode`; its main thread was idle. Ordinary SIGTERM to exact PID `38632` did not exit it.
  Attempt two was canceled before a completed suite; only after all test clients exited, one guarded SIGKILL
  removed that exact daemon. Attempt three used a new daemon, PID `90564`, and reproduced the same initialization
  failure. No further retry was launched. `/usr/bin/automationmodetool` with no arguments reported Automation Mode
  disabled and user authentication required. Authentication was not disabled; TCC, SIP and credentials were not
  modified by this recovery. Xcode's GUI also requested its required system components; normal installation was
  started and remained waiting for other installation tasks. Computer-use safety blocked `com.apple.SecurityAgent`,
  so the local authentication window was handed off to the owner. Approval for HeyTim access was already recorded;
  the remaining authentication request is not a renewed permission question.
- **PENDING — native execution:** Terminal metadata discovery returned Apple Event timeout `-1712`; no command
  was submitted. An isolated unsaved TextEdit fixture remained unchanged because native Accessibility observation
  returned zero controls with fallback title `Untitled window`. Independent computer-use observation still read
  its exact seed text. System Settings accepted a signed HeyTim→Terminal Allow record, but showed the switch off
  after subsequent discovery requests; that observation does not establish the cause of the timeouts. Native
  diagnostics/error-reporting corrections are prepared in PR #141, pending the shared gate and a new signed
  candidate. Direct computer-use control of Terminal was also blocked by tool safety; it was not bypassed to run a
  command. These observations supersede the earlier unanswered-grant status below, but do not establish successful
  Terminal execution or desktop editing. Public Apple publication and physical iPhone/APNS verification remain
  unchanged from the initial rollout below.

## 2026-10-15 — Chief defaults, teammate routing, and Mac Terminal

- [PR #136](https://github.com/tmoreton/heytim/pull/136) merged as
  `cfcbaf23c8931631e3abe86ddfe8fccf19b3c88f`. Chief v9 has 12 compatible built-in tools and 17 official skills;
  bots support up to 20 skills. The signed-in owner's Chief also showed those counts with its existing prompt and
  model preserved. Local Mac grants remain separate from the bot's tool selection.
- [Backend rollout 38773634059](https://github.com/tmoreton/heytim/actions/runs/38773634059) succeeded in the
  dedicated production account. Runtime 493, API 718, integrity evaluator two, and CDK ten tests passed. All five
  managed regression sessions completed without invocation/session failures; GoalSuccessRate and ResponseRelevance
  each averaged 1.0 across five evaluations. Evaluation artifact `11994485048` retains the evidence.
- The authenticated workflow and three-turn webhook smoke passed with cleanup. The new Chief smoke passed
  `chief_defaults`, `credit_preflight`, `chief_create`, `chief_edit`, and `chief_routing`: three Chief turns created
  and edited a temporary bot, then routed one task whose exact reply was verified in the target chat. Scoped cleanup
  succeeded. Website and production API catalogs both returned Chief v9, 12 tools, 17 skills, and `mac_terminal`.
- [Apple CI 38770763421](https://github.com/tmoreton/heytim/actions/runs/38770763421) passed 161/161 native tests
  with zero failures/skips: 128 Mac unit, seven Mac UI, and 26 iPhone UI tests. Artifact `11991893837` retains xcresults.
  Its tested source `955c40b` has the same Git tree as the merged release. The original PR's service and security
  checks also passed. Duplicate queued main-native/server runs were canceled; production server verification and the
  private Apple workflows ran their own gates.
- [Private Mac candidate 38775428149](https://github.com/tmoreton/heytim/actions/runs/38775428149) passed its
  production-configured Apple gate, Developer ID export, app and DMG notarization, stapling, and Gatekeeper checks.
  Receipt artifact `11996147017` identifies **1.1.1 / 20261015172350**, source `cfcbaf23`. Independent installation
  checks matched its DMG SHA-256 `ddbe6e719b4c3eb396078ea6912def26d074b1e74372492f18faf709e3cb59e9`, production
  configuration, team/bundle identity, and Apple Events entitlement. The installed update passed signature, staple,
  and Gatekeeper checks again. Version 1.1.0 remains in an owner-only rollback directory outside `/Applications`.
- Internal iPhone attempt [38776816463](https://github.com/tmoreton/heytim/actions/runs/38776816463) failed before
  upload. Its 128 Mac unit tests passed, but XCTest timed out initiating a daemon control session before any Mac UI
  case began (error 8, xcodebuild 65). Signing cleanup restored the original keychain list. The same source had passed
  the preceding private Mac gate. A fresh single-case probe also stalled before test startup and was stopped (75).
  After confirming no active test clients, one SIGTERM to the exact user-owned native `testmanagerd` process let
  macOS recreate it. The cached composer/layout case then passed in 23.646 seconds (exit 0); its result is retained
  under `/tmp/HeyTimMacUIInitializationRecheck-20261015-1828/mac-ui-after-daemon.xcresult`. SIP, TCC, and credentials
  remained unchanged. [Internal iPhone retry 38788280531](https://github.com/tmoreton/heytim/actions/runs/38788280531)
  passed all 161 native tests (128 Mac unit, seven Mac UI, 26 iPhone UI; zero failures/skips) against the same source
  and uploaded **1.1.1 / 20261015184612** for internal-only TestFlight processing. Submission receipt artifact
  `11999303112` retains the exact source and destination. Signing cleanup restored the login keychain and removed
  the temporary signing keychain. Xcode's upload success was recorded at 19:06:03 UTC. Read-only inventories
  [38791306361](https://github.com/tmoreton/heytim/actions/runs/38791306361) and
  [38791645935](https://github.com/tmoreton/heytim/actions/runs/38791645935) did not yet list the new build at
  19:07/19:10 UTC. Both confirmed one accepted/installed owner in the all-builds internal group and zero other testers;
  those runs do not establish the new build's processing status or audience. Final inventory
  [38792321134](https://github.com/tmoreton/heytim/actions/runs/38792321134) confirmed the exact build as
  **VALID / INTERNAL_ONLY**, uploaded at 19:07:04 UTC, with the same one-owner/zero-other-tester review.
- **PENDING — live installed-app Terminal/computer smoke:** the owner session shows version
  **1.1.1 / 20261015172350** and desktop connection **Connected**, but the global Terminal/app-action switches remain
  off and Accessibility is not granted. The access confirmation is unanswered, so no new grants or live Terminal
  commands were attempted. Public Apple publication and its approval flags remain unchanged; the signed Mac installer
  is retained privately on the canonical host. Physical iPhone installation and APNS delivery are not proved by upload.

## 2026-10-15 — Pebble webhooks and Mac-local routing

Software is deployed, and the installed-app signed-webhook/duplicate-replay smoke passed with a persisted answer.
Physical Pebble voice capture remains **PENDING**; the full hardware objective is not yet verified.

- [PR #130](https://github.com/tmoreton/heytim/pull/130), merged as `a1666c2`, added secure account-owned
  Pebble/generic JSON sources, durable dispatch and Mac-local bot/reasoning routing. Fixed routes can answer
  without the Mac; local routes wait for it, with an optional owner-selected fallback preserving saved reasoning.
  [PR #133](https://github.com/tmoreton/heytim/pull/133) (`f920eadc`) refreshes already-selected conversations.
  [PR #134](https://github.com/tmoreton/heytim/pull/134) finalized explicit transcript-snapshot observation and
  reply-visibility regressions at `15bc18fc2630a55875d915456680f7908656a2ba`; its Mac wheel-test change preserves
  all original assertions, waits and iPhone gestures.
- [Backend rollout 38630219572](https://github.com/tmoreton/heytim/actions/runs/38630219572) passed deployment
  checks, five managed regression sessions (both evaluators averaged 1.0), the normal four-turn workflow and three
  webhook turns covering signed nested JSON, simulated Mac selection, fallback, replay/test suppression,
  disable/rotation and cleanup. Checks included 700 Python tests, nine smoke mocks and four token-vault policy
  checks; API/Apple production configuration matched. The deployed backend remains unchanged at `a1666c2`.
  Those cloud-routing choices were simulated; the installed-app evidence below is separate.
- Final [Apple CI 38666369388](https://github.com/tmoreton/heytim/actions/runs/38666369388) passed
  **150/150, zero failures/skips**: 117 Mac units, seven Mac UI and 26 iPhone UI tests; artifact `11942482123`
  retains xcresults. Merged tree `f89d8649cf3032c0c7cc5e70ca0725d1e017a142` exactly matches verified `389f214`.
  [Services 38666369411](https://github.com/tmoreton/heytim/actions/runs/38666369411) passed its classifier;
  five unchanged product jobs were **skipped**, not newly executed suite passes. GitGuardian passed.
- **Installed Mac:** [candidate 38668374255](https://github.com/tmoreton/heytim/actions/runs/38668374255),
  `1.1.0` build `20261015015721`, exact source `15bc18f`, passed its 150-test native gate, signing and
  notarization. Independent DMG verification passed 61 native signatures, 57 distribution versions/provenance
  checks, frozen helper/model identity and production configuration, stapling and Gatekeeper. Installation exited 0;
  rollback is retained with no remaining staging app or mount. Owner sign-in and Local Routing **On / Ready**
  were observed. The permanent Pebble Index source uses local routing, the current sole permitted bot Chief,
  and an explicit Chief fallback. The older signed `a1666c2` candidate is historical and superseded.
- **Internal iPhone software:** [upload 38671650776](https://github.com/tmoreton/heytim/actions/runs/38671650776)
  succeeded after 150 native tests with zero skips. Version `1.1.0`, build `20261015023422`, uploaded at
  02:53:20 UTC; receipt artifact `11945226974` is retained. [Inventory 38673872086](https://github.com/tmoreton/heytim/actions/runs/38673872086)
  returned the exact build as **VALID / INTERNAL_ONLY** and the sole accepted/installed Apple Account Holder in
  an all-builds group, with zero other testers. Preflight inventory `38671489984` passed; earlier target-absent
  inventory `38673488945` remains retained. These fields do not prove physical installation or additional
  beta-detail availability.
- **Installed-app smoke:** a signed Pebble-format request and its exact duplicate both returned HTTP 202 for
  event `f06e9b6f-7b30-5b2f-91cb-67b00e5ba88d`. One incoming row progressed **Routing → Queued** without manual
  intervention or a fallback badge, using the unchanged local source. The bundled helper's RSS grew from
  approximately 22 MB during health-only operation to 797 MiB during delivery. Opening Chief showed **42**, the
  unique test marker and effective **Low** reasoning; Chief's saved **High** preference remained unchanged.
  Reopening through Webhooks forced a fresh load and still showed one event, one assistant node
  (`3a9ca1bd-0bf9-510d-ab30-fd688d33912c`) and exactly two marker copies (question/answer), with the same 42/Low
  result. Local acceptance and the Low override are inferred from source policy and UI evidence; raw decision
  method/probabilities were not exposed. This protocol smoke does not prove physical ring capture.
- Credentials were saved in the canonical private bundle with directory/file modes 0700/0600 using data-only
  TextEdit and linked privately to the owner. The editor and one-time credential sheet are closed. The sender
  consumed credentials through stdin, without secret argv/output. Terminal-app automation was denied by tool
  safety review and never used or bypassed. No credentials are included in this entry.
- Prior failures remain retained: iPhone candidate `38641755423` stopped at 25/26 before upload; Mac candidate
  `38657614616` stopped before signing after an omitted offline reply. Diagnostics reproduced four model
  messages but no fourth-message transcript update; temporary hooks were removed before the snapshot fix.
  Earlier OS-alert failures and both Mac swipe-synthesis failures in Apple `38663623484` are separate evidence.
  Native wheel input then passed three focused runs with 12 positive-600-pixel actions, all original assertions
  and no fallback/retry before final CI passed.
- Model/helper/weights/fixtures remain frozen: route and effort concentration cutoffs `0.60`, route margin `0.15`.
  Across 53 development/calibration cases, 42 accepted routes and 28 automatic effort choices were correct,
  but two subsets failed effort coverage. The independent final eight-case set failed both coverage gates:
  only two of six routable requests were accepted, both correct, with one correct automatic effort choice.
  No retuning followed. Limited coverage does not establish production accuracy; uncertainty retains explicit
  fallback or manual review.
- The advisory audit found no known advisories among 55 locked registry dependencies, including Torch `2.13.0`.
  It excludes the pinned Strands Git archive and bootstrap `pip 26.0.1`, which has four recorded CVEs in
  installation/download/self-update paths. App execution does not invoke/import pip; official-wheel provenance
  was verified. This is not a whole-bundle zero-advisory claim; the existing CDK finding remains documented.
- **PENDING — physical voice:** the owner was asked to configure Pebble from the private bundle and send
  “17 plus 25, include pebble amber seven”; the response is awaited. Phone notifications are optional per the
  latest instruction, and physical APNs display/tap remains unverified. Public distribution approvals are
  unchanged. Private receipts/failure evidence remain under `output/webhook-routing/`. Update this entry after physical
  voice verification; the full objective remains incomplete until that result is recorded.

## 2026-10-09 — verified production recovery

- Merged [PR #123](https://github.com/tmoreton/heytim/pull/123) and
  [PR #124](https://github.com/tmoreton/heytim/pull/124), ending at
  `0bb6b26f0c4a96984a7c7331cb46a72a175e9638`. Backend and security CI passed.
  The pinned synthetic fixture now has a metered 300-credit monthly allowance in the exact dedicated destination;
  customer free limits remain 30. The release check fails before mutations when fewer than four credits remain.
- [Production recovery rollout 38001583301](https://github.com/tmoreton/heytim/actions/runs/38001583301)
  succeeded from `0bb6b26`: AgentCore and Amplify deployment, production resource checks, all five managed
  regression sessions, and the complete authenticated attachment/schedule/share/approval/cleanup workflow passed.
  Both managed evaluators scored all five sessions 1.0, with no failed or ignored sessions.
  The earlier failed rollout and fixture-quota check remain recorded below.
- The preserved generated Apple client configuration exactly matches `/Applications/HeyTim.app`, version
  `1.0.19` build `20261009214232`. Its UI source is unchanged from the verified `752d386` candidate.
  The website and public catalog remain healthy. Public publication remains pending the existing compliance
  and physical notification-open gates; both protected flags still read `false`. The `v1.0.19` release remains
  an unpublished draft with no public binaries, and the live public updater remains `v1.0.12`.

## 2026-10-09 — browser recovery, Mac layout, and accessibility fixes

- Merged [PR #121](https://github.com/tmoreton/heytim/pull/121) as
  `a253203a7c3caf7fbe8475f28e14f955cfe49486` and
  [PR #122](https://github.com/tmoreton/heytim/pull/122) as
  `752d3867caaefc7f9bafcccbe0c23f5e822187b4`. The Mac chat column now contains
  its browser panel without clipping the composer behind the sidebar. Expired browser handoffs expose inline
  recovery that preserves the draft and waits for confirmed success. Completed-reply usage metadata remains
  accessible without triggering the reproduced SwiftUI accessibility crash.
- [Production backend deployment 37986357343](https://github.com/tmoreton/heytim/actions/runs/37986357343)
  passed in destination account `820323452649`, including all five managed AgentCore regression scenarios and
  the authenticated production workflow. The destination API remains
  `https://srrkqsqrqd.execute-api.us-east-1.amazonaws.com` with Cognito pool `us-east-1_biJejrNQF`.
- The merged source passed [Apple verification 37994686234](https://github.com/tmoreton/heytim/actions/runs/37994686234):
  97 Mac unit tests, four Mac UI tests, six transcription tests, and a generic iPhone build. This host has no iOS
  Simulator runtime; a generic build is not evidence of a physical-device notification test.
- [Private Mac candidate 37994687001](https://github.com/tmoreton/heytim/actions/runs/37994687001) produced
  version `1.0.19`, build `20261009214232`, from `752d386`. Developer ID signing, app and DMG notarization,
  stapling, Gatekeeper, and destination client-configuration checks passed. The owner-authorized local installation
  at `/Applications/HeyTim.app` received the requested live test reply from the destination backend. Accessibility
  inspection through reply completion and browser-panel navigation succeeded, and the existing unsent draft was
  preserved. This private installer did not publish a GitHub release or change the Sparkle feed. Version `1.0.18`
  was superseded after reproducing the accessibility crash and must not be promoted.
- [Website deployment 37998005111](https://github.com/tmoreton/heytim/actions/runs/37998005111) succeeded from
  `752d386`, including website verification, the marketing site, and the secure browser viewer.
- [Backend rollout 37998002979](https://github.com/tmoreton/heytim/actions/runs/37998002979) deployed
  `752d386` to AgentCore and Amplify and passed resource checks and all five managed regression scenarios
  with scores of 1.0. Its final authenticated workflow failed when the scheduled reply ended in an error;
  the attachment step had passed. This run is not a successful release verification. A separate protected,
  main-only production smoke workflow now permits targeted rechecking without another deployment and
  summarizes only sanitized runtime failure categories, exception types, and code locations.
- [Targeted production check 38000782671](https://github.com/tmoreton/heytim/actions/runs/38000782671)
  passed attachments, scheduled replies, and sharing, but failed before the second approval proposal.
  The synthetic account started with 27 of its 30 monthly credits consumed; the preceding three turns consumed
  its remaining allowance. Temporary resources were cleaned up, and the sanitized runtime-marker query returned
  no failures. This later quota failure is separate from the earlier scheduled runtime-client error.
- [Read-only Apple inventory 37998007356](https://github.com/tmoreton/heytim/actions/runs/37998007356) confirmed
  the HeyTim listing name, privacy URL, and iOS support URL match. The newest existing iPhone build is `1.0.16`,
  build `20261002171304`, processed `VALID` with audience `INTERNAL_ONLY`. The Apple Account Holder is accepted
  in an internal group with access to all builds. The optional account-deletion URL remains unlinked in Apple's
  metadata; the public deletion guidance is available on the website. A read-only mailbox check found the
  October 1 synthetic support delivery test in the owner's Inbox, addressed to `support@heytim.ai`, mailed through
  `eforward.registrar-servers.com`, and signed by `heytim.ai`. This establishes the alias forwarded that test
  successfully; no new email was sent.
- Public distribution remains pending: `HEYTIM_RELEASE_COMPLIANCE_APPROVED` and
  `HEYTIM_APNS_DEVICE_SMOKE_APPROVED` both read `false`. The prior device evidence established provider-accepted
  notification delivery, but not tapping the notification into its intended conversation. An unpublished
  `v1.0.19` release draft targets the verified application commit `752d386` and has no attached public binaries.
  The latest public download and Sparkle feed remain `v1.0.12` until the public release gates pass. Unapproved
  Google, Slack, Notion, and X connections remain disabled, and this fresh launch remains free.

## 2026-10-01 — fresh destination launch and Apple release in progress

- An October 1 read of Google Auth Platform's Verification Center showed **HeyTim branding verified and shown to
  users**, while **data access remains unverified** for `youtube.readonly`, `gmail.readonly`, and `gmail.compose`.
  Google's submission screen still requires scope justifications, intended data usage, and a demonstration video;
  none of the four Google/X/Slack/Notion production connection/review flag pairs was enabled. The X production app
  `33430000` was renamed from FroggyBot to **HeyTim by tmoreton**, and its public website, organization, terms, and
  privacy links were updated to `heytim.ai` and verified after saving. Its new destination OAuth callback was already
  registered; older callbacks remain for rollback. The signed-in Slack dashboard exposed an unrelated ZEUS app: its
  client ID did not match the Slack client ID held in either production account. No Slack app setting was changed.
  The signed-in Notion developer page remained stuck on loading placeholders, so its callback and distribution status
  could not be verified. App Store Connect requested a fresh Apple sign-in on refresh; the signed-in GitHub run summary
  separately showed iOS build `20261001055358` as `VALID` and `INTERNAL_ONLY`, with the Account Holder accepted in an
  all-builds internal group. The same summary found that the optional App Store account-deletion URL was blank;
  `https://heytim.ai/account-deletion/` is already live, and account deletion is initiated in the app's Settings.
  The installed Mac app also reported an expired session.
- The owner chose a fresh, free launch in destination AWS account `820323452649`, retaining source account
  `188757775631` for rollback without transferring customer records or tokens. The destination public API at
  `https://srrkqsqrqd.execute-api.us-east-1.amazonaws.com` returned the HeyTim catalog on October 1. Production
  [backend-only run 36806967998](https://github.com/tmoreton/heytim/actions/runs/36806967998) succeeded with the
  managed five-scenario regression and authenticated workflow checks. Unapproved Google, X, Slack, and Notion
  connections remain disabled.
- The GitHub repository is `tmoreton/heytim`, its Pages domain is `heytim.ai`, and the GitHub App is presented as
  HeyTim. Legacy protected credential handles and the `frogbot-macmini` runner registration remain in place for
  compatibility; release jobs select the `heytim-apple` runner label. The annotated `v1.0.13` tag and unpublished
  draft release target current main commit `620c2b9a7b302b38613b65e6defc5f80a604936e` and have no public assets.
- Read-only [App Store Connect inventory 36825304305](https://github.com/tmoreton/heytim/actions/runs/36825304305)
  passed: the HeyTim listing name, privacy URL, and support URL match; the Apple Account Holder is accepted or
  installed in an internal group with access to all builds. The App Privacy label is drafted but unpublished.
  DNS points `heytim.ai` mail to Namecheap forwarding, but the `support@heytim.ai` alias destination and delivery
  remain unverified. Both `HEYTIM_RELEASE_COMPLIANCE_APPROVED` and `HEYTIM_APNS_DEVICE_SMOKE_APPROVED` remain `false`.
- The first internal iPhone upload [run 36808752688](https://github.com/tmoreton/heytim/actions/runs/36808752688)
  failed before upload when its temporary signing keychain locked after two hours of native compilation. Main commit
  `620c2b9` extends that timeout to six hours. The corrected internal-only
  [retry 36821645378](https://github.com/tmoreton/heytim/actions/runs/36821645378) succeeded on October 1 and
  submitted iOS `1.0.13` build `20261001055358` to App Store Connect. Its private receipt pins the source to
  `620c2b9`, destination account `820323452649`, and destination API. The upload log says Apple's package is
  processing; this is submission evidence, not processing completion or availability on a device. A later
  [read-only inventory 36839073340](https://github.com/tmoreton/heytim/actions/runs/36839073340) again verified
  the Account Holder's accepted membership in the all-builds internal group. Its GitHub Actions job summary showed
  iOS `1.0.13` build `20261001055358` processed as `VALID` with audience `INTERNAL_ONLY`. This confirms Apple
  processing and internal group eligibility, but not installation or push delivery on a physical iPhone. The private
  [Mac candidate 36821899708](https://github.com/tmoreton/heytim/actions/runs/36821899708) subsequently
  succeeded for `1.0.13` build `20261001084651`, also from `620c2b9` and the destination AWS configuration.
  Its nonsecret receipt (artifact `11154275607`) records the signed DMG, Sparkle ZIP, and signed appcast checksums.
  Apple accepted notarization of both the app and DMG; signature, stapling, Gatekeeper, and mounted-image checks
  passed. The runner removed the signed binaries and left the GitHub release as a draft with zero assets. This
  private run's Apple verification used Mac unit tests plus a generic iPhone build, since its runner has no iOS
  Simulator runtime. It did not prove physical push delivery or publish a Sparkle update.
- Later on October 1, App Store Connect showed the iOS `1.0.13` build in **Testing** for the internal group. With the
  owner's specific approval, the App Privacy label was published; App Store Connect displayed “Published a few seconds
  ago by Timothy Moreton.” It lists 13 data types linked to the user for app functionality, tracking off, and
  `https://heytim.ai/privacy/` as the privacy URL. Namecheap's `heytim.ai` panel showed the `support` redirect-email
  alias forwarding to the owner's Gmail and Mail Settings set to **Email Forwarding**. An end-to-end support email
  delivery check remains outstanding.
- The owner installed the internal iPhone build and reported that notifications worked. A read-only destination AWS
  check found one production iOS APNs token updated at `2026-10-01T14:08:50Z`, one endpoint under the HeyTim APNs
  application, and none under the legacy application. SNS recorded a delivery at `14:12:58Z` with
  `ACCEPTED/PROVIDER_ACCEPTED`. Tapping the notification to open the intended conversation was not yet confirmed.

## 2026-09-30 — capture infrastructure staged; traffic cutover NO-GO

- The source account `188757775631` still serves customers and accepts mail. No source write freeze, customer-state
  copy, API/provider traffic switch, TestFlight upload, or Sparkle publication occurred. The source preflight, after
  correcting AWS CLI empty-response handling, performed 45 checks and reported 31 NO-GO findings. A later fix for
  CloudFormation's bare SES receipt-rule physical ID cleared one false finding on live read-only rerun; 30 remain,
  including the receiver hold, writer fences, Memory settlement, and external webhook inventory. Some are
  intentional evidence gates rather than independently clearable settings.
- Separate, termination-protected `HeyTimSourceMailCapture` and `HeyTimDestinationMailCapture` stacks reached
  `CREATE_COMPLETE` in their exact accounts. Their reviewed diffs added encrypted 14-day SQS capture/failure queues,
  private retained quarantine buckets, SNS subscriptions, and narrow SES role grants without replacing or deleting
  an existing resource. Controlled non-mail SNS messages reached each capture queue and were removed by exact ID;
  both capture and failure queues then read empty. The temporary retention exception and cleanup gate are recorded
  privately at `/private/tmp/heytim-mail-capture-retention-exception-20260930.json`.
- Destination SES still has no active receipt rule set. The destination mail receiver was set to zero reserved
  concurrency and its existing SNS subscription received the reviewed `MessageAttributes` hold filter; the separate
  SQS capture subscription remains unfiltered. The 15-minute read-only CloudTrail hold proof passed. The inactive
  destination `HeyTimBotInbox` rule was pointed at the standalone quarantine bucket with its recipient, topic,
  and role preserved. The source SES rule and source mail receiver were not held or changed. The live destination
  full-backend capture preview was addition-only for resource identity (`+9/~16/-0`, zero replacements), but remains
  NO-GO because it contains unrelated resource modifications and IAM statement changes that need review.
- `HeyTimMemoryCapture` reached `CREATE_COMPLETE` in the source account with a seven-day encrypted Kinesis stream,
  retained encrypted archive, and enabled consumer. Source Memory remains `ACTIVE` with **no stream attached**.
  A source-specific candidate template added only FULL_CONTENT stream delivery, but the live CloudFormation change
  set also proposed four indirect dynamic modifications to the runtime and online evaluation resources. The
  fail-closed reviewer rejected it; the change set was deleted without execution. AgentCore still has no proven
  terminal extraction marker or conditional late-record update path, so strict no-loss migration remains NO-GO.
  A narrowly scoped direct `UpdateMemory` tool passed read-only preparation against the live source, but no
  `UpdateMemory` call was made. It would create deliberate CloudFormation drift and cannot prove uninterrupted
  data-plane service or complete delivery; its mutation remains a separate decision.
- The read-only [App Store Connect inventory](https://github.com/tmoreton/heytim/actions/runs/36672428588)
  succeeded using protected credentials. It found five recent iOS builds and an internal tester group; it did not
  upload a build or verify device delivery. The prior Apple verification run was still actively compiling both
  apps, and obsolete queued private candidates were canceled for replacement from final main. Sparkle
  remained at `v1.0.12`. Google branding and data-access reviews were still unverified; all four unapproved
  provider connections remained disabled.
- The integrated migration branch passed 175 script tests plus 13 subtests, 590 API tests plus 43 subtests,
  focused Memory and App Store Connect tests, Python lint, TypeScript type checking, and the source-size check.
  These checks verify staging code; they do not clear the live cutover or publication gates.

## 2026-09-29 — isolated-account cutover preparation

- The source account `188757775631` remains live; no customer traffic, Apple clients, provider webhooks, or production
  GitHub environment variables have switched to destination account `820323452649`.
- The destination backend and AgentCore resource checks passed with the candidate outputs. A destination recovery drill
  restored and verified a DynamoDB point-in-time table and an S3 object version, then removed the temporary table.
- Read-only migration inventories found 638 current source application records, 1,012 file object versions and 13
  delete markers across both source buckets, and AgentCore memory with four actors, 16 sessions, 187 events, and 404
  long-term records. The destination application table and memory remain empty. Migration tools and private identity
  maps are prepared for a fresh write-frozen snapshot; these numbers are not final cutover checksums.
- After hardening the migration identity checks and provider-state exclusions, a new read-only DynamoDB plan again
  found 638 source rows, 625 retained rows, and 13 excluded connection/device/push rows. Its source and plan digests
  are checkpoints only; both must be regenerated after writes stop. The destination API Lambda currently points Google
  and GitHub callbacks at the destination API and uses `https://heytim.ai` as its public site. Stripe remains disabled
  in that Lambda until the subscription identity and webhook cutover is complete.
- A new read-only S3 plan, with Cognito-derived actor checks, again found 295 HeyTim source keys, 455 versions, and one
  delete marker for the canonical-and-archive pass. Separate dry runs of the transient-result retention backfill found
  nine untagged result versions in the HeyTim source bucket and none in the legacy source or destination bucket. No
  tags or lifecycle rules have been applied in AWS; review the backfill only after migration and rollback planning.
- Google saved the destination OAuth callback while retaining source callbacks. The consent app, OAuth client label,
  and Cloud project display name now show HeyTim. The website serves a Search Console tag that verified ownership of
  `https://heytim.ai/`. Google still reports branding and data access unverified. Its branding retry requires waiting
  24 hours after ownership verification; sensitive YouTube and restricted Gmail scopes require subsequent review.
  A warning-free Google sign-in is **not** verified.
- The destination `heytim/stripe/production` secret was created by an in-memory copy of the existing live credential
  bundle and verified by readback; no values were printed. The live Stripe webhook, subscription user metadata, and
  GitHub App webhook still point to the source. An attempt to remove Google's obsolete `froggybot.com` authorized
  domain was blocked by automatic approval review after Google said an OAuth client still uses that domain. The
  proposed removal was not saved.
- A fresh live audit found the source application table at 638 rows and the destination application table and memory
  still empty. The source table digest changed between two read-only scans despite stable row counts, confirming that
  customer writes are ongoing. No customer data migration or write freeze has begun. A read-only reconciliation found
  the one live Stripe subscription and its customer, Price, status, period, and source user mapping match the source
  billing record; the destination billing path is still disabled and no Stripe setting was changed.
- Google's Verification Center still marks HeyTim branding and data access unverified and does not offer submission
  until branding verification is complete. The authorized destination callback is saved, but it is not Google approval.
  On September 29 the protected GitHub production flags for Google review, physical-device APNs smoke, and release
  compliance were corrected from `true` to `false` and read back as `false`. The account-cutover flag remains absent.
- After explicit owner approval on September 29, the Plaid production application credential was copied in memory
  from the source account to protected destination Secrets Manager and read back for exact value parity. Only
  `clientId`, `secret`, and `environment=production` were transferred; no customer Plaid tokens moved. Destination
  Plaid access and webhooks remain disabled until cutover verification.
- A repository-wide hostname audit found no `froggybot.com` or `frogbot.com` URL in live app, website, API, catalog,
  AgentCore configuration, scripts, or workflows. Public web and in-app links use `heytim.ai`. The checked-in active
  API and Apple outputs still use the source AWS API endpoint; the destination endpoint is staged as a candidate,
  not live. The GitHub App homepage and Google's obsolete authorized-domain entry remained external settings to
  resolve at this checkpoint. Later on September 29, the GitHub App homepage alone was changed to
  `https://heytim.ai/` and verified on its public page. The destination GitHub OAuth callback was then added alongside
  the source callback; the setup URL and webhook still point to the source API. After explicit owner approval, the
  destination X OAuth callback was also added beside both existing X callback URLs. Neither provider webhook moved.
- The latest published Apple release remains `v1.0.12`. Local `./scripts/apple-app.sh build` passed for iPhone and Mac,
  and `./scripts/apple-app.sh verify` completed successfully on both platforms on September 29 after the new workflow
  and release-script changes. Destination-configured iPhone and Mac candidate workflows are being prepared without
  publishing TestFlight or the Mac Sparkle release. No new Apple version has been uploaded from this checkpoint.
- The first internal TestFlight dispatch, [run 36618354768](https://github.com/tmoreton/heytim/actions/runs/36618354768),
  was canceled while its sole job was queued, before signing or upload. Apple permits automatic distribution to
  internal groups and makes eligible builds available to App Store Connect Users; even an internal-only upload could
  expose the empty destination account before migration. The revised pre-cutover workflow builds and checks a signed
  candidate without uploading it to TestFlight. The repository is public, so signed binaries are not retained as
  downloadable Actions artifacts.
- Cutover-readiness and provider-gating code landed on `main` as `5adc721`, followed by the source-size correction
  `520df09`. The iPhone and Mac destination-only version `1.0.13` candidates from `520df09` are
  [run 36652160673](https://github.com/tmoreton/heytim/actions/runs/36652160673) and
  [run 36652172869](https://github.com/tmoreton/heytim/actions/runs/36652172869); both were queued at this
  checkpoint, with no TestFlight upload or Sparkle publication. The earlier iPhone candidate from `f4f24fb`
  signed and exported an IPA locally but failed its portable receipt parser; its replacement has that fix.
- Destination production flags for Google, Slack, Notion, and X connections and their review attestations were
  read back as `false`. This hides unverified or unconfigured connections after the destination backend is deployed;
  it does not change the live source service. The source remains writable and no customer-data copy has begun.
  A third source file bucket used by AgentCore contained 208 versions and six delete markers at read-only inventory.
  The main HeyTim source bucket continued gaining versions, so all file and table manifests need a frozen refresh.
- The source write-freeze preflight returned 39 checks and 30 blockers. A guarded read-only capture stopped at
  AgentCore Memory because its resource-policy response did not prove absence versus unsupported policy behavior.
  No source settings were changed. A local Apple verification on the concurrently edited shared workspace compiled
  both platforms and passed Mac tests, but its iPhone UI suite reached the 1,200-second timeout; the clean committed
  candidate jobs are the release check for this revision.
- The September 29 preparation checkout also passed 42 migration tests (plus three subtests), 66 focused runtime
  tests, the API verification gate (including 568 backend tests), all 10 AgentCore CDK tests, API typecheck, Python
  lint/format checks, and the Apple architecture/source-size gate. These local checks do not substitute for the
  protected CI and provider/device checks required before release.

## 2026-09-23 — Home Assistant backend-only rollout

- Merged [PR #58](https://github.com/tmoreton/heytim/pull/58) as commit `b029fd796c87cb1871c4b5643dd5d3d51be4038c`. The required application, runtime, AgentCore, Apple, dependency, and security checks passed.
- [Production run `35865295766`](https://github.com/tmoreton/heytim/actions/runs/35865295766) completed successfully from `main` with `release_scope=backend-only`. It updated the AgentCore runtime and Amplify backend and passed the protected production resource checks. This scope did not upload TestFlight builds or produce a new Mac DMG.
- Home Bot's Home Assistant connection is connected and its per-bot tool switch is on. The separate Mac app actions switch is also on, with Accessibility granted and the bundled local model reporting ready in the installed 1.0.3 app.
- Before this rollout, a direct Assist MCP test of the exact Bedroom Light succeeded: its initial `off` state was read, `HassTurnOn` returned success and state `on`, then `HassTurnOff` returned success and state `off`. The test restored the initial state. This proves the connection and exposed Assist actions, not the bot/Laya path.
- A read-only Home Bot request immediately after the rollout was rejected before agent invocation because the owner account had used all 30 of 30 free work credits; the app says the allowance resets September 30, 2026. Thus the deployed bot path, Laya route, and live on/off through HeyTim remain **unverified**. Do not treat the direct MCP check or the green deployment as evidence that those paths work end to end.

## 2026-09-18 — workflow, routine, workspace, and approval release

- Released commit `2bc8fed` as [`v6.2.5`](https://github.com/tmoreton/frogbot/releases/tag/v6.2.5).
  [Production run `35357358258`](https://github.com/tmoreton/frogbot/actions/runs/35357358258) passed its release
  gates, 454 API/worker tests, 266 runtime tests, dependency audit, AgentCore deployment, Amplify deployment, and
  production resource verification. Local AgentCore validation and Apple unit tests also passed; the native release
  runner passed the iPhone UI suite. Python and JavaScript/TypeScript CodeQL analysis passed.
- The separate website/catalog CI job identified a 600-line source-size gate in three touched backend modules.
  Commit `6845192` moved their functions into focused modules without changing behavior. The full hosted
  [verification run](https://github.com/tmoreton/frogbot/actions/runs/35361014024) and CodeQL passed. A
  [backend-only production run](https://github.com/tmoreton/frogbot/actions/runs/35361037087) deployed that exact
  commit and passed service checks, dependency audit, AgentCore/Amplify deployment, and resource verification.
  The signed webhook smoke check passed again against the updated API.
- The production API accepted a correctly signed synthetic GitHub `issues.opened` delivery and replay with HTTP 202
  (`matchedRoutines: 0`) and rejected a bad signature with HTTP 401. This verifies signature handling for the issue
  route, but no routine matched, so it does not verify routine deduplication. After account confirmation, the GitHub
  App webhook was activated at the production `/public/webhooks/github` URL with SSL verification enabled. Its secret
  was set to the matching 48-byte random value stored in `frogbot/oauth/github-production`, and the App was subscribed
  to Issues events. The GitHub App API confirmed the URL, JSON format, configured secret, and `issues` event. A real
  GitHub `installation.new_permissions_accepted` webhook delivery reached the production endpoint and received HTTP
  200 (`{"accepted":false}`), as expected for an event outside the issue routine trigger. A live `issues.opened`
  delivery with a matching routine remains untested.
- The release runner uploaded both iPhone and Mac TestFlight packages for version `6.2.5`, build `20260918145216`,
  to App Store Connect. Apple's processing and availability in TestFlight must still be checked there.
- The cloud computer remains deferred. Durable bot/room files use the existing encrypted S3 storage and explicit
  Code Interpreter sync; this release does not provision an always-on computer. Live room concurrency, one-use
  approval resume, and workspace sync still need a disposable production pilot before broad activation.

## 2026-09-14 — Mac message recovery and native TestFlight refresh

- Committed release revision `8cbe7ab`. CloudWatch tied the Mac desktop “Something went wrong” response to an old
  `connection_*` tool ID copied with the production bot while OAuth connections were intentionally excluded from the
  owner migration. Removed the four migrated bots' stale connection references and verified all 10 production bots now
  contain zero stale connection IDs. Runtime and API execution also filter unavailable stored tools so a revoked or
  non-migrated connection cannot make an otherwise ordinary message fail.
- Moved editable bot identity and prompt settings onto the main native Details page above its conversation controls,
  replaced the Edit Bot row with Tools & Skills, and switched Details and every native subpage to the compact centered
  navigation title. The focused iPhone Details-page UI regression and the macOS application suite passed.
- Enabled every bot to create and attach a private skill for itself during an explicit direct user conversation. The
  capability cannot grant new tools, run from a schedule, mutate another bot, or publish the skill. Installed
  `JOP Newsletter Voice & AI-Tell Review` as production skill `skill-0eeb70c63f964883afa0` on JOPbot; its review is
  explicitly heuristic and does not claim to determine authorship.
- AgentCore validation, Python lint, all 219 runtime tests, and all 378 backend tests passed. The full native wrapper
  completed its transcription and Mac suites, but the local Xcode 26.6 iOS runner again failed to materialize the test
  worker because its LLDB registry reported `DebuggerVersionStore.StoreError` / `no debugger version`. The focused
  iPhone regression had already passed on the same app change, and both signed Release archives subsequently compiled
  and passed store validation.
- Deployed the existing `AgentCore-FrogBot-production` runtime in place, preserving
  `FrogBotProduction_FrogBotMemory-FWrlGD61iY`, then updated Amplify app `d1tu46ki1836w1`. The runtime reports `READY`,
  the CloudFormation stacks report `UPDATE_COMPLETE`, the public catalog responds successfully, and all five AgentCore
  alarms remain present. The aggregate production verification remains blocked only by the already-recorded missing
  confirmed subscriber on the service-alarm topic.
- Uploaded matching iPhone and Mac TestFlight packages for version `6.0.0`, build `202609141145`, bundle
  `com.frogbot.app`, and team `GVXC5FQ2RP`. App Store Connect accepted the iPhone upload at 11:45 AM EDT and the Mac
  upload at 11:48 AM EDT and began processing both packages.

## 2026-09-14 — temporary management-account production deployment

- Temporarily retargeted production to management account `188757775631` in `us-east-1` while the dedicated member
  account Lambda quota request remains open. Deployments used the assumed `FrogBotDeploymentRole`, never AWS
  account-root credentials, and require the explicit `FROGBOT_ALLOW_SHARED_PRODUCTION_ACCOUNT=true` safeguard.
- Deployed `AgentCore-FrogBot-production` with the target-scoped `FrogBotProduction` physical namespace. Runtime
  `FrogBotProduction_FrogBot-WAhqXM7v63` and gateway
  `frogbotproduction-frogbottools-psxeb1nzdt` reported `READY`; encrypted memory
  `FrogBotProduction_FrogBotMemory-FWrlGD61iY`, all three memory strategies, and the continuous evaluation reported
  `ACTIVE`. Regression dataset version 1 published all five expected examples.
- Deployed Amplify app `d1tu46ki1836w1` and stack
  `amplify-d1tu46ki1836w1-main-branch-6ca713cbb2`. Its public API is
  `https://twrxzanvwg.execute-api.us-east-1.amazonaws.com`; both tracked Swift client configurations now identify the
  environment as `production` and use that API.
- Verified DynamoDB deletion protection and point-in-time recovery, versioned encrypted production storage, 30-day
  customer-key-encrypted AgentCore logs, worker reserved concurrency of 10, five `OK` AgentCore alarms, enabled APNs
  production/sandbox applications with delivery feedback, and a healthy public catalog containing 15 bots, 15 skills,
  and seven built-in tools. The aggregate deployment check remains correctly blocked because the new alarm topic has
  no confirmed accountable subscriber.
- Updated the GitHub production environment with the new Amplify app, generated least-privilege OIDC deployment role,
  production memory key, shared-account safeguard, quotas, APNs applications, Apple team, and AgentCore credentials.
  Human/provider/compliance/device approval flags were deliberately left unset.
- Updated the production Google secret callback metadata to
  `https://twrxzanvwg.execute-api.us-east-1.amazonaws.com/public/oauth/google/callback`. Google and the other provider
  consoles still require their production callback/distribution approvals before public release.
- Created a confirmed, email-verified production identity for the release owner and migrated its durable content from
  the development environment without changing the source account. The verified copy includes 10 bots, 45 direct-chat
  turns, two groups with 124 messages, 28 stored files (21.8 MB), one custom skill, three production-targeted schedules,
  161 AgentCore conversation events, and all 334 extracted long-term memory records. Stale device push tokens, browser
  sessions, usage counters, notification deliveries, and development OAuth credentials were deliberately excluded.
- AgentCore validation, generated CDK tests, 216 runtime tests, and 373 backend tests passed before deployment. The
  TestFlight gate passed the transcription package and macOS application suites. Xcode 26.6's headless runner still
  could not launch the iOS UI suite because its host LLDB registry repeatedly returned
  `DebuggerVersionStore.StoreError` / `no debugger version`, even with the focused UI-test scheme using the non-debug
  launcher. The same scheme completed all 16 iOS UI tests in Xcode on iOS 26.2 with zero failures; the shared scheme
  and its project generator now preserve that non-debug launcher configuration.
- Created production-configured iPhone and Mac archives for version `6.0.0`, build `202609140210`, bundle
  `com.frogbot.app`, and team `GVXC5FQ2RP`. Both archives compiled and signed successfully with the available Apple
  Development identity. The initial command-line export stopped before transmission because Xcode could not use its
  stale signed-in account credentials (`missing Xcode-Token`). After the local Xcode account was refreshed, Organizer
  uploaded both archives to App Store Connect and confirmed `Uploaded to Apple` at 8:45 AM for iPhone and 8:51 AM for
  Mac. Both TestFlight builds are now awaiting Apple's processing.

## 2026-09-13 — production account bootstrap (Lambda quota pending)

- Created the dedicated AWS Organizations member account `820323452649` (`FroggyBot Production`) and bootstrapped
  CDK in `us-east-1` with termination protection. Production deployments use the member account's
  `FroggyBotOrganizationAccessRole`; account-root credentials are not used for application resources.
- Created a rotating customer-managed AgentCore memory key, isolated copies of the configured provider secrets, the
  production Amplify app `d17sj7dvhx07c`, and production/sandbox SNS APNs platform applications for
  `com.frogbot.app`.
- Deployed `AgentCore-FrogBot-production`. Runtime `FrogBot_FrogBot-3pPvmu2ODl` and gateway
  `frogbot-frogbottools-muu7bqevxo` reported `READY`; encrypted memory
  `FrogBot_FrogBotMemory-T17d4eBnCx` reported `ACTIVE`; the evaluator and five-percent online evaluation reported
  `ACTIVE`. The corrected regression dataset source published five examples to the managed draft.
- The first Amplify backend create reached the worker Lambda and then rolled back because AWS assigned the new member
  account only 10 regional concurrent executions. The production worker reserves 10 and Lambda requires additional
  unreserved capacity. Quota request `6c0b66ca52be4a4cbb809df314bb0ecbFAR2XZbA` opened support case
  `178934881900679` for 1,100 concurrent executions; its status remained `CASE_OPENED` at the end of this run.
- Verified the failed create contained no users or table records, removed its failed CloudFormation stack and empty
  retained data artifacts, and scheduled only its three orphaned KMS keys for deletion on 2026-09-20. The production
  AgentCore stack, Amplify app, provider secrets, APNs applications, and APNs delivery logs were preserved.
- Xcode 26.6 recognized Apple team `GVXC5FQ2RP`, bundle `com.frogbot.app`, release version `6.0.0`, and both native
  archive plans. Actual iOS/macOS archives remain gated on a successful production backend so no TestFlight build can
  accidentally embed development client configuration.

## 2026-09-13 — production release-readiness audit (not deployed)

- Made the shared SwiftUI target the production release surface: the controlled workflow no longer requires Expo or
  publishes web output, and a dependent macOS job verifies once before uploading matching iPhone and Mac TestFlight
  builds from the exact production backend configuration.
- Preserved the existing integration work in commit `299359c`, then audited the repository, GitHub controls, current
  AgentCore development state, AWS alarms/logging/budget, and production configuration. No production deployment was
  attempted: the available AWS identity was account root, the production target was not deployed, and required
  production values and accountable external approvals were absent.
- AgentCore validation passed; two evaluator tests, six CDK tests, 216 runtime tests, and 373 backend tests passed.
  Dependency audits reported zero known npm or Python vulnerabilities.
- Shared/web client tests, type checks, lint, Expo Doctor, production-preview exclusion, bundle budgets, and exported
  security-header checks passed. The transcription package's three Swift tests and the macOS app unit suite passed.
  The local iOS UI runner could not launch because Xcode 26.6 repeatedly reported a host LLDB “no debugger version”
  error; the test command is now bounded, and the macOS GitHub runner remains the release gate for that suite.
- The GitHub production environment was restricted to `main`, repository vulnerability alerts were enabled, and CI
  dependency installation/uv/CodeQL artifact handling were repaired. Environment reviewers remain unavailable on the
  current private-repository plan.
- A dedicated production member account (`820323452649`) was created after the audit. Production still fails closed
  until monitored alarms and APNs feedback are verified, provider/compliance/device attestations are complete, and
  the production workflow passes end to end.

## 2026-09-05 — us-east-1

- Forty authenticated bootstrap requests at concurrency eight returned HTTP 200 with zero failures and 2.12-second p99
  latency against the five-second gate.
- A disposable-account workflow passed attachment upload/read, schedule create/run/delete, share create/revoke,
  interactive approval deny and allow-once, cancellation, temporary-bot cleanup, and account deletion.
- DynamoDB point-in-time restore and S3 selected-version restore passed. All temporary recovery resources were removed.
- Budget notifications at 50% and 80% actual spend and 100% forecast were connected to the encrypted service alarm
  topic. A human or incident-system subscription was still pending.
- A synthetic telemetry marker appeared in no CloudWatch event payload. Its corresponding Strands trace events stored
  `[REDACTED]`.
- The work queue and dead-letter queue were empty, disposable identities were removed, and all eight service alarms
  returned to `OK` through their normal evaluation windows.
