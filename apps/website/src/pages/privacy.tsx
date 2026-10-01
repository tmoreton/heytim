export function Privacy() {
  return (
    <main className="doc-page" id="main">
      <p className="eyebrow">HeyTim</p>
      <h1>Privacy Policy</h1>
      <p className="effective">Effective October 1, 2026</p>
      <p>This policy explains what HeyTim collects, why we use it, and the choices available to you.</p>

      <h2>Information we collect</h2>
      <p>We collect the email address used for passwordless authentication, bot configurations, conversation messages, and basic service records needed to operate and secure HeyTim.</p>
      <p>Our API keeps access logs for 30 days. These records include the request time and route, your IP address, response status and latency, and technical errors. We use them to maintain service reliability and security.</p>
      <p>If you turn on a bot inbox, we collect email sent to that bot’s address, including the sender and recipient addresses, subject, message text, and attachment names. We briefly store the original email, including any attachments, while processing it. Messages in the bot inbox are available for you to review and delete; the bot does not act on them automatically.</p>
      <p>If you choose phone-number sign-in, we collect the mobile number you provide and a record of your SMS consent. Providing a phone number and consenting to SMS are optional because email sign-in remains available.</p>
      <p>If you allow reply notifications, we store a device push token and a delivery identifier. The current iPhone and Mac apps register Apple device tokens with Amazon Simple Notification Service (SNS), which sends notifications through Apple Push Notification service (APNs). Older app versions that use Expo may still receive notifications through Expo. On supported Apple devices, dictation is requested as on-device speech recognition; HeyTim does not intentionally upload or retain the audio recording.</p>

      <h2>How we use information</h2>
      <p>We use this information to authenticate you, save bots and conversations, run requested agents, deliver notifications, prevent abuse, and maintain the service. Mobile numbers are used only to send user-requested one-time passcodes and related verification messages.</p>
      <p>HeyTim does not sell personal information. Mobile numbers and SMS opt-in or consent data are not shared with third parties or affiliates for their own marketing or promotional purposes.</p>

      <h2>AI processing and connected accounts</h2>
      <p>When you ask a bot to work, your message and relevant conversation history, files, and connected-service results may be processed by HeyTim’s agent service on Amazon Web Services and sent through OpenRouter to AI model providers for an answer, draft, or generated content. The model provider can vary by request or fallback. This processing can include personal information.</p>
      <p>Before a bot can use third-party AI processing, HeyTim asks for your permission. You can turn it off in Settings → Data &amp; Privacy → Turn Off AI Processing. This stops new AI work and stops a running task before its next model-provider request. Turning it off does not delete content already saved in conversations, files, memory, or tool results.</p>
      <p>On iPhone, if you grant Apple Health access and enable it for a bot, that bot can request activity, workout, running, and daily-step summaries for your task. The app sends the resulting summary to HeyTim’s API for the bot to use. It may be sent through OpenRouter to an AI model provider and included in saved conversations, generated files, bot memory, or stored tool results. A bot response or file shared in a group can make those details visible to other members. This feature does not read or send routes, individual sensor samples, or clinical records. You can turn off Apple Health for a bot in its settings or revoke the app’s Apple Health permission to prevent future reads; doing so does not erase previously saved results.</p>
      <p>When Google connections are available, you can connect Gmail, YouTube, or Google Workspace and assign each connection to bots you choose. HeyTim stores the connection record and refresh credential in AWS Secrets Manager. An assigned bot may read information permitted by the grant to respond to your request; Gmail bots may also create drafts for your review.</p>
      <p>Information returned by a connected service can appear in saved conversations, generated files, bot memory, and stored tool results. If you use a connected bot in a group, its answers or shared files can make some of that information visible to other group members.</p>
      <p>Disconnecting an account prevents new bot requests from using that connection. HeyTim attempts to revoke the provider grant and schedules its stored credential for deletion. Disconnecting does not erase information already included in conversations, files, stored tool results, or memories.</p>

      <h2>Connected financial accounts</h2>
      <p>When Plaid connections are available, connecting a financial institution is optional. You choose the institution in Plaid Link and which accounts and HeyTim bots can use the connection. Your bank sign-in happens with Plaid or your financial institution; HeyTim does not receive your bank username or password.</p>
      <p>HeyTim stores a scoped Plaid access token in AWS Secrets Manager, plus your connection and account details. We import and update your transactions in private, account-scoped storage. Assigned bots can read those transactions and request account details, balances, and supported credit liabilities. Financial information used in a bot request may be sent through OpenRouter to the selected AI model provider and may appear in saved conversations, files, or bot memory. If you use the bot in a group, information included in its answers or shared files may be visible to other group members.</p>
      <p>Disconnecting the institution stops future access, requests removal of the Plaid connection, schedules deletion of its stored access token with a seven-day recovery period, and queues deletion of the stored transaction history, including its saved versions. Financial information already included in conversations, files, or bot memory remains until you delete that content. Account deletion starts broader cleanup of your account data.</p>

      <h2>Service providers and sharing</h2>
      <p>HeyTim uses Amazon Web Services for account services, agent processing, data storage, and native notification delivery through Amazon SNS; Apple APNs to deliver notifications to current iPhone and Mac apps; Plaid for optional financial connections; OpenRouter and AI model providers for requested bot output; and Stripe for existing subscription billing where applicable. Older app versions may use Expo for notification delivery. Relevant user text and connected-service content can be included in requests routed through OpenRouter.</p>
      <p>When you use paid billing, HeyTim stores your Stripe customer and subscription identifiers, subscription status and renewal period, and work-credit usage. Stripe processes payment details; HeyTim does not receive or store your full card number.</p>
      <p>If you create a share link, anyone with a valid link may be able to import its content, so treat share links as private. Group members can see messages and files shared in their group, including information in a bot’s response even though the underlying account connection belongs to you.</p>

      <h2>SMS choices</h2>
      <p>HeyTim sends one transactional verification code only after you request one. Message frequency varies, and message and data rates may apply. Reply <strong>STOP</strong> to opt out or <strong>HELP</strong> for help. For US toll-free messages, text <strong>START</strong> or <strong>UNSTOP</strong> to the sending number to re-enable messages after opting out. See the <a href="/sms/">HeyTim SMS program</a> and <a href="/terms/">Terms of Use</a> for details.</p>

      <h2>Retention and choices</h2>
      <p>We retain account content and consent records while needed to provide HeyTim, comply with legal obligations, resolve disputes, or protect the service. Bot inbox previews remain until you delete them or your account; original received email is stored temporarily for processing. You can turn off or replace a bot’s email address from its inbox. You can stop notifications in device settings and sign out at any time.</p>
      <p>You can request permanent account deletion from Account settings in the iPhone or Mac app. This starts cleanup of your account and the content it owns. Content shared into a group owned by someone else may remain available to that group. Operational backups expire according to their limited retention schedule. <a href="/account-deletion/">Learn how account deletion works.</a></p>

      <h2>Security, children, and changes</h2>
      <p>We use administrative and technical safeguards designed to protect information, but no online service can guarantee absolute security. HeyTim is not directed to children under 13.</p>
      <p>Questions about this policy or your account can be sent to <a href="mailto:support@heytim.ai">support@heytim.ai</a>. We may update this policy as the service changes. The effective date identifies the current version.</p>
    </main>
  );
}
