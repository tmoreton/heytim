# Public launch checklist

This checklist separates repository publication, licensing, product access, and
production operations. They are related, but none should silently stand in for
the others.

## Repository and community

- [x] The canonical repository is publicly visible.
- [x] The complete Git history passes Gitleaks with no unignored findings.
- [x] GitHub secret scanning and push protection are enabled.
- [x] Security, support, conduct, issue, and pull-request guidance are published.
- [x] Dependency updates and CodeQL analysis are automated.
- [x] Protect `main` from force pushes and deletion without disrupting the current
  direct-push release workflow.
- [ ] Decide whether every change must use a pull request before enabling that
  stronger requirement.
- [ ] Decide whether external implementation pull requests are accepted and, if
  so, publish the contributor agreement and enable safe CI for forks.

## Licensing decision

The repository currently uses PolyForm Noncommercial 1.0.0. That makes HeyTim
source-available, not OSI open source. Before describing the project as open
source, choose and document one model:

1. Keep PolyForm Noncommercial and consistently say **source-available**.
2. Adopt an OSI-approved license such as Apache-2.0, with a deliberate decision
   about commercial use, patents, contributor terms, and third-party notices.

Changing the license requires the copyright holder’s explicit approval and a
review of the commercial-license strategy. Do not change only the marketing
language.

## User acquisition

- [x] The website explains the product, private-beta state, supported Apple
  platforms, bot library, privacy policy, terms, support, and access-request path.
- [x] Production, iPhone TestFlight, and direct Mac releases are reproducible from protected workflows.
- [ ] Choose private invite review, a waitlist, or a public TestFlight link as the
  initial acquisition model.
- [ ] Add the chosen access destination to the website and measure request,
  invitation, activation, and retention conversion without collecting unnecessary
  personal data.
- [ ] Define the first cohort size, onboarding owner, support capacity, and rollback
  threshold before widening access.

## Production gate

- [ ] Complete the production smoke workflow, provider checks, recovery drill,
  alert-delivery test, and evidence record described in
  [`production-release.md`](production-release.md).
- [ ] Confirm the current iPhone TestFlight build finishes App Store Connect processing
  and its privacy/export-compliance answers match deployed behavior.
- [ ] Invite users gradually and monitor authentication, queue failures, runtime
  errors, email complaints, notification delivery, cost, and account deletion.
