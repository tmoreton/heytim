import { useEffect, useState } from 'react';
import { invitationAppLink } from './catalog';
import { TimIcon } from './tim-icon';
import { Icon } from './icon';

export function OpenApp({ invite = false }: { invite?: boolean }) {
  const [link, setLink] = useState<string | undefined>(invite ? undefined : 'heytim://');
  useEffect(() => { setLink(invite ? invitationAppLink(window.location.search) : 'heytim://'); }, [invite]);
  return <main className="download-page wrap" id="main">
    <section className="download-heading"><TimIcon size={88} /><p className="eyebrow">A little team. Right at home.</p>
      <h1 className="page-title">{invite ? <>Good company<br /><em>starts here.</em></> : <>Meet your team.<br /><em>Make yourself at home.</em></>}</h1>
      <p className="page-intro">{invite ? 'You’ve been invited to HeyTim. Open your invitation in the app to join in.' : 'A native app for your iPhone and Mac. The same team, wherever life takes you.'}</p>
      {link ? <a className="button-secondary open-installed" href={link}>Open {invite ? 'invitation' : 'installed app'} in HeyTim <Icon name="diagonal" size={18} /></a>
        : invite ? <p className="invite-status" role="status">Use your complete invitation link. If it no longer works, ask the sender for a fresh invitation.</p> : null}
      {invite ? <noscript><p>Enable JavaScript to open your personal invitation in HeyTim. Your invitation token stays in this page’s URL.</p></noscript> : null}
    </section>
    <div className="download-options">
      <article><Icon name="laptop" size={32} /><span className="download-platform">FOR YOUR DESK</span><h2>HeyTim for Mac</h2><p>Room for the whole team, with native Mac app actions, private browser sessions, and on-device dictation.</p><a className="button" href="https://github.com/tmoreton/heytim/releases/latest">Get the Mac download <Icon name="diagonal" size={18} /></a><span className="download-requirement">macOS 14 or later · Download the DMG from Releases</span></article>
      <article><Icon name="phone" size={32} /><span className="download-platform">FOR EVERYWHERE ELSE</span><h2>HeyTim for iPhone</h2><p>Pick up conversations on the go, dictate an idea, and connect Health Coach to activity summaries you choose to share.</p><a className="button" href="mailto:support@heytim.ai?subject=HeyTim%20iPhone%20beta%20access">Request iPhone access <Icon name="arrow" size={18} /></a><span className="download-requirement">iOS 17 or later · Private beta through TestFlight</span></article>
    </div>
    <aside className="beta-access"><div><h2>A small team, opening the doors a little at a time.</h2><p>HeyTim accounts are currently invitation-only, including for the Mac app. Already invited on iPhone? Install HeyTim from your TestFlight invitation. Need an account or a hand getting started?</p></div><a className="text-link" href="mailto:support@heytim.ai?subject=HeyTim%20beta%20access">Request beta access <Icon name="arrow" size={18} /></a></aside>
  </main>;
}
