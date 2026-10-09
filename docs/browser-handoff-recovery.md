# Browser handoff recovery

Browser display status and chat send eligibility describe different things. A
remote session can expire while its stored handoff still belongs to the user.
Returning `expired` from GET must not silently release that handoff or hide the
action required before chat can continue.

The browser response now includes `blocksSending`, computed from the same
persisted-state predicate as the direct-send preflight. An expired human
handoff therefore returns `status: "expired"`, `blocksSending: true`, and
`recoveryRequired: true`. A ready browser that expires without a handoff can
return `blocksSending: false`. GET remains read-only and never issues a live
viewer capability.

The native chat shows an inline notice when a handoff blocks sending. It keeps
the draft and attachments, disables Send, and offers Open Browser or End Browser
Handoff. The latter calls the existing close endpoint, preserves saved login
profiles, and does not submit the draft or re-enqueue a continuation. The
separate Forget saved login action retains its existing destructive semantics.
The browser panel offers Resume Bot during human control and Reopen Browser for
expired sessions. An in-progress operation must finish before it can be ended.

Uncertain continuation, profile-save, and remote-operation states keep the
existing fail-closed behavior. Recovery does not infer safe termination from a
local timeout, remove the send guard, or automatically repeat external work.
Late status responses cannot restore a blocker after a confirmed close, and
responses from a previous signed-in session cannot update the next session.

For independent client/server rollouts, `blocksSending` is optional in the
native decoder. Older expired responses are treated conservatively until
explicit recovery. The old handoff error is recognized alongside the new
`browser_handoff_incomplete` code and becomes an inline notice rather than an
unactionable modal.

On Mac, the browser panel lives within the visible detail column's layout.
Its content does not contribute a window-level title or toolbar menu. Hide
browser panel only changes visibility; End Browser Handoff changes the session.

## Verification

Run `./scripts/apple-app.sh verify` for both Apple platforms. On a Mac without
an iOS simulator runtime, `HEYTIM_ALLOW_GENERIC_IOS_BUILD=true` permits an iOS
compile and reports that distinction. The gate includes Mac unit tests and
targeted Mac UI tests for expired-handoff recovery, draft preservation, composer
bounds with the browser shown/hidden, Details bounds, and toolbar ownership.
The UI runner uses a separate verification bundle ID and local ad hoc signing.

Backend coverage includes expired human and ready sessions, explicit close
without profile deletion or continuation, uncertain resume, stored/display
status consistency, ownership, and existing concurrent-operation protections.
