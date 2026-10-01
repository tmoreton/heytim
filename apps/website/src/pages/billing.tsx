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
    <p className="eyebrow">HeyTim billing</p>
    <h1>{successful ? 'Billing redirect received' : 'Return to HeyTim'}</h1>
    <p>{successful
      ? 'The current fresh beta offers only the Free plan. An earlier Stripe checkout does not automatically change your current account. Contact support@heytim.ai if you have a question about a charge or earlier subscription.'
      : 'Open the app to check your current plan and work-credit balance.'}</p>
    <p><a className="button" href={appURL(status)}>Open HeyTim</a></p>
    <p className="effective">New Plus checkout and subscription management are unavailable in this release.</p>
  </main>;
}
