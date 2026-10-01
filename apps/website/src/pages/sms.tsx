export function Sms() {
  return (<main className="doc-page" id="main">
    <p className="eyebrow">Transactional authentication</p><h1>SMS verification program</h1>
    <p>SMS sign-in is not available in the current HeyTim beta. Sign-in and account creation use email verification. HeyTim is not sending sign-in texts or collecting SMS sign-in consent in this release.</p>
    <p>HeyTim is an independent software product operated by Timothy Moreton. It helps individuals and groups organize conversations, decisions, and useful files. The proposed SMS program below is for optional, user-requested passwordless sign-in and account verification if phone sign-in becomes available. It would not send promotional or marketing text messages.</p>

    <div className="program-meta"><strong>Planned program:</strong> HeyTim one-time passcodes<br /><strong>Message frequency if launched:</strong> One message per login attempt; frequency varies<br /><strong>Customer care:</strong> Reply HELP for help or visit https://heytim.ai/sms/<br /><strong>Opt out:</strong> Reply STOP</div>

    <h2>Proposed opt-in flow</h2>
    <p>This flow is not in the current app. If SMS sign-in becomes available:</p>
    <ol>
      <li>A user would choose phone-number sign-in or account creation in HeyTim.</li>
      <li>The user would enter a US mobile number.</li>
      <li>The user would affirmatively select a separate, unchecked SMS consent checkbox before requesting a code.</li>
      <li>HeyTim would send one verification code for that login attempt.</li>
    </ol>
    <p>Email sign-in is currently available. A phone number and SMS consent are not required to use HeyTim.</p>

    <section className="sms-panel" aria-labelledby="consent-title">
      <p className="eyebrow">Proposed example, not a current app screen</p>
      <h2 id="consent-title">Sign in with your phone</h2>
      <p>Enter your mobile number and we’ll send a six-digit verification code. No password needed.</p>
      <p><strong>Mobile phone number</strong><br />+1 (201) 555-0123</p>
      <div className="consent-example">
        <span className="checkbox-example" aria-label="Unchecked consent checkbox"></span>
        <p>I agree to receive HeyTim one-time passcode and verification texts at the mobile number provided. One message per login attempt; message frequency varies. Message and data rates may apply. Reply STOP to opt out or HELP for help. Consent is not a condition of purchase. See our <a href="/privacy/">Privacy Policy</a> and <a href="/terms/">Terms of Use</a>.</p>
      </div>
    </section>

    <h2>Proposed message examples</h2>
    <p>“HeyTim: Your verification code is [code]. It expires in 10 minutes. Msg frequency varies. Msg &amp; data rates may apply. Reply HELP for help, STOP to opt out.”</p>
    <p>“HeyTim: [code] is your sign-in code. Expires in 10 min. Do not share. Msg frequency varies. Msg &amp; data rates may apply. Reply STOP to opt out, HELP for help.”</p>

    <h2>STOP and HELP</h2>
    <p>If the SMS program launches, reply STOP to opt out. For US toll-free messages, the carrier blocks future messages after STOP. Text START or UNSTOP to the sending number to re-enable future verification messages. Reply HELP for customer-care information.</p>
    <p>Mobile carriers are not liable for delayed or undelivered messages. For information about how mobile numbers and consent records are handled, read the <a href="/privacy/">Privacy Policy</a>.</p>
  </main>);
}
