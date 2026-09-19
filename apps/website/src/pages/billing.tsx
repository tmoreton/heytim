import { useEffect, useState } from 'react';

function appURL(status: string) {
  const safeStatus = ['success', 'canceled', 'return'].includes(status) ? status : 'return';
  return `heytim://app?billing=${safeStatus}`;
}

export function BillingReturn() {
  const [status, setStatus] = useState('return');

  useEffect(() => {
    const value = new URLSearchParams(window.location.search).get('status') ?? 'return';
    setStatus(value);
    const timer = window.setTimeout(() => { window.location.href = appURL(value); }, 250);
    return () => window.clearTimeout(timer);
  }, []);

  const successful = status === 'success';
  return <main className="doc-page" id="main">
    <p className="eyebrow">HeyTim Plus</p>
    <h1>{successful ? 'You’re all set.' : 'Return to HeyTim'}</h1>
    <p>{successful
      ? 'Stripe is confirming your subscription. Your plan and work-credit balance will refresh in the app.'
      : 'Your plan was not changed. You can return to the app whenever you’re ready.'}</p>
    <p><a className="button" href={appURL(status)}>Open HeyTim</a></p>
    <p className="effective">You can manage or cancel a subscription from Usage &amp; Plan in HeyTim settings.</p>
  </main>;
}
