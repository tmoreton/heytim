# HeyTim GitHub App cutover — 2026-10-01

The fresh free-account launch uses the existing GitHub App, ID `4931494`, owned by
`tmoreton`. Its public name and slug are **HeyTim by tmoreton** and
`heytim-by-tmoreton`. The existing installation `161399020` remains attached
to the same App ID. The App homepage points to `https://heytim.ai/`.

On 2026-10-01, the App webhook URL was changed from
`https://twrxzanvwg.execute-api.us-east-1.amazonaws.com/public/webhooks/github`
to
`https://srrkqsqrqd.execute-api.us-east-1.amazonaws.com/public/webhooks/github`.
GitHub readback confirmed the destination URL, JSON payload format, and TLS
certificate verification. The App ID, client ID, owner, and installation were
unchanged. The existing App secrets in AWS accounts `188757775631` and
`820323452649` have matching App identity, `heytim-by-tmoreton` slug, and
webhook signing key; no credential value was printed or copied during this
cutover.

Before switching GitHub, the destination webhook returned `401` for an invalid
signature and `200` for a correctly signed `ping` payload without starting a
routine. GitHub had no recent deliveries available for a provider-generated
redelivery check. A new signed GitHub delivery and an end-to-end connection
test remain necessary before treating GitHub issue routines as verified.
The App's OAuth callback and post-installation settings should also be read
back in its owner settings before claiming the connection flow is verified.

For rollback, change only the existing App webhook URL back to the source URL
above, then verify GitHub's readback and delivery status. Keep the App ID,
installation, signing key, JSON format, and TLS verification unchanged. The
old GitHub App slug is not assumed to redirect; use the current HeyTim slug
for installation links in either account.
