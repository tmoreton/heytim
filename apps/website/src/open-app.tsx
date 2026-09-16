import { useEffect, useState } from 'react';
import { invitationAppLink } from './catalog';

export function OpenApp({ invite = false }: { invite?: boolean }) {
  const [link, setLink] = useState<string>();
  useEffect(() => { setLink(invite ? invitationAppLink(window.location.search) : 'frogbot://'); }, [invite]);
  return <main className="doc-page" id="main">
    <p className="eyebrow">FroggyBot for iPhone and Mac</p>
    <h1>{invite ? 'You’re invited.' : 'Your team, in the app.'}</h1>
    <p>Conversations now live in the FroggyBot Apple app. This website is home to the public bot and skills library.</p>
    {link ? <a className="button" href={link}>Open in FroggyBot <span aria-hidden="true">↗</span></a>
      : invite ? <p role="status">Open this page using your complete invitation link. If it no longer works, ask the sender for a fresh invitation.</p> : null}
    <h2>Need the app?</h2>
    <p>FroggyBot is in private beta through TestFlight. Already a tester? Open TestFlight on your iPhone or Mac and install the latest FroggyBot build.</p>
    <a className="button-secondary" href="mailto:tmoreton89@gmail.com?subject=FroggyBot%20beta%20access">Request beta access</a>
  </main>;
}
