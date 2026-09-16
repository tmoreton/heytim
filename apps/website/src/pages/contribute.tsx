export function Contribute() {
  return (<main className="doc-page" id="main">
    <p className="eyebrow">Open contribution guide</p>
    <h1>Add a bot people can trust.</h1>
    <p>A ready-made bot is a small configuration: a clear name, a focused prompt, and references to any existing skills or tools it needs. There is no separate bot code to maintain.</p>

    <h2>Before you start</h2>
    <ul>
      <li>Search the <a href="/library/">bot directory</a> and existing pull requests so you do not duplicate a bot.</li>
      <li>Choose one clear user outcome. “Plan a group trip” is stronger than “be helpful.”</li>
      <li>Never put API tokens, passwords, or other secrets in the catalog. FroggyBot supplies any shared-service credentials; private account data uses provider OAuth.</li>
    </ul>

    <h2>Submit a bot</h2>
    <ol>
      <li><a href="https://github.com/tmoreton/frog-bots/fork">Fork Frog Bots</a> on GitHub.</li>
      <li>Add one bot entry to <code>catalog.json</code>, following the closest existing example.</li>
      <li>Write a focused prompt, reference existing skill IDs, and list only tools the bot directly requires. The app decides model and speed settings.</li>
      <li>Add realistic scenarios and expected behavior in <code>bots/&lt;bot-id&gt;/evals.json</code>.</li>
      <li>Run <code>python3 scripts/validate_catalog.py</code>.</li>
      <li>Open a pull request. The checklist will guide the usefulness, clarity, safety, and least-privilege review.</li>
    </ol>
    <p><a className="button" href="https://github.com/tmoreton/frog-bots">View the bot repository</a></p>

    <h2>Contribute a supporting skill</h2>
    <p>Skills stay in the codebase as reusable, readable instructions that multiple bots can share. If a bot needs a new way of working, add a focused <code>SKILL.md</code>, register it in <code>catalog.json</code>, and reference it from the bot.</p>
    <p><a className="button-secondary" href="https://github.com/tmoreton/frog-bots/issues/new?template=skill-request.yml">Request a skill</a></p>

    <h2>Propose a tool</h2>
    <p>Tools can access services or take actions, so they require server-side implementation and a stricter review. Start with a tool request that states:</p>
    <ul>
      <li>the user outcome and exact actions;</li>
      <li>what information the tool reads, stores, or changes;</li>
      <li>how authentication works and where credentials live;</li>
      <li>whether each action is read-only, sandboxed, or interactive; and</li>
      <li>the smallest permissions that can support the use case.</li>
    </ul>
    <p><a className="button-secondary" href="https://github.com/tmoreton/frog-bots/issues/new?template=tool-request.yml">Propose a tool</a></p>

    <h2>What happens after review</h2>
    <p>Accepted bots appear in the directory without an app release. Installing one creates a private, editable copy; future catalog changes do not rewrite it. Supporting skills remain versioned so existing bots stay predictable.</p>
  </main>);
}
