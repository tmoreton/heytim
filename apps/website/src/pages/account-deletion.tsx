export function AccountDeletion() {
  return (
    <main className="doc-page" id="main">
      <p className="eyebrow">Your account</p>
      <h1>Delete your HeyTim account</h1>
      <p>You can start permanent account deletion directly in HeyTim for iPhone or Mac.</p>

      <h2>How to delete your account</h2>
      <ol>
        <li>Sign in to the HeyTim app.</li>
        <li>Open Settings and find the Account section.</li>
        <li>Select Delete Account and confirm the request.</li>
      </ol>
      <p>The app signs you out after the deletion request is accepted. The service then processes account cleanup. Deletion cannot be undone.</p>

      <h2>What deletion includes</h2>
      <p>Deletion removes your account identity and the HeyTim content it owns, including bots, private chats and memory, files, connected accounts, schedules, skills, invitations, shared links, and groups you own. Connected-account access is revoked where supported. Groups you own are removed for their members.</p>
      <p>Content you shared into a group owned by someone else may remain available in that group. Some records may be retained where needed for legal obligations, disputes, or service security, and operational backups expire on their limited retention schedule. See the <a href="/privacy/">Privacy Policy</a> for details.</p>

      <h2>If you cannot sign in</h2>
      <p>Contact <a href="mailto:support@heytim.ai?subject=HeyTim%20account%20deletion">support@heytim.ai</a> for help with an account deletion request. Include the email address associated with your account; we may need to confirm that the account is yours.</p>
    </main>
  );
}
