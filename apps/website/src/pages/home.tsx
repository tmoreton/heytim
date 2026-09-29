import catalog from '../../../../catalog/catalog.json';
import { availableEntries } from '../catalog';
import { TimIcon } from '../tim-icon';
import { Icon } from '../icon';
import { ProductDemo } from '../product-demo';
import { GetStarted } from '../site-chrome';

const { bots, skills } = availableEntries(catalog);
const teamIds = ['chief', 'trip-planner', 'research-reports', 'youtube-studio', 'mac-operator'];
const featured = teamIds.flatMap((id) => bots.filter((bot) => bot.id === id));
const providers = [
  ['gmail', 'Gmail'], ['google_workspace', 'Google Workspace'], ['slack', 'Slack'],
  ['github', 'GitHub'], ['notion', 'Notion'], ['youtube', 'YouTube'],
];

export function Home() {
  return <main id="main">
    <section className="hero wrap" aria-labelledby="hero-heading">
      <div className="hero-copy">
        <p className="eyebrow"><span className="eyebrow-rule" />A little team for your whole life</p>
        <h1 id="hero-heading">Your life.<br />With a little<br /><em>backup.</em><span className="hero-asterisk" aria-hidden="true">✳</span></h1>
        <p className="hero-intro">Meet the AI team that remembers what matters, works with your people, and turns “we should” into something done.</p>
        <div className="hero-actions"><a className="button" href="/download/">Find your little team <Icon name="arrow" /></a><a className="text-link" href="#how-it-works">See how it works <span aria-hidden="true">↘</span></a></div>
        <p className="hero-platforms"><Icon name="laptop" size={17} /><Icon name="phone" size={15} /><span>At home on iPhone & Mac. Currently in private beta.</span></p>
      </div>
      <ProductDemo />
    </section>

    <div className="possibility-strip" aria-label="Ways to use HeyTim"><div className="wrap"><span>Big trips.</span><i aria-hidden="true">✳</i><span>Daily rituals.</span><i aria-hidden="true">✳</i><span>Fresh ideas.</span><i aria-hidden="true">✳</i><span>Shared decisions.</span><i aria-hidden="true">✳</i><span>Life, handled together.</span></div></div>

    <section className="section wrap" id="how-it-works" aria-labelledby="how-heading">
      <div className="section-heading split-heading"><div><p className="eyebrow">More than a conversation</p><h2 id="how-heading">A team that gets you.<br /><em>And gets to it.</em></h2></div><p>Start with Chief, your coordinator. Add specialists for the things you care about. Give them context once, then keep building on it.</p></div>
      <div className="difference-grid">
        <article className="memory-feature">
          <span className="feature-number">01 / A little understanding</span><h3>Less explaining.<br />More “you remembered.”</h3><p>Your preferences, your projects, your way of doing things. Memory carries the useful details into your next conversation, and you can review, edit, or delete them.</p>
          <div className="memory-notes" aria-label="Example memory"><div><Icon name="memory" /><span>Our trips start with a train ride.</span><Icon name="check" size={16} /></div><div><Icon name="memory" /><span>My writing should sound like me.</span><Icon name="check" size={16} /></div><div><Icon name="memory" /><span>Keep the morning brief short.</span><Icon name="check" size={16} /></div></div>
          <a className="text-link" href="/features/#memory">Memory you control <Icon name="arrow" size={18} /></a>
        </article>
        <article className="together-feature">
          <span className="feature-number">02 / A little togetherness</span><div className="together-avatars" aria-hidden="true"><span className="person-avatar">J</span><span className="person-avatar second">S</span><TimIcon size={62} /><TimIcon color="#3984F6" size={62} /></div><h3>Your people.<br />Meet your AI people.</h3><p>Bring friends, family, or teammates into one group. Ask Chief, bring in the specialists, and save the decisions you reach together.</p>
          <div className="shared-decision"><Icon name="check" /><div><strong>One plan everyone can come back to.</strong><span>Shared context, files, and saved decisions.</span></div></div>
          <a className="text-link" href="/features/#together">Made for doing things together <Icon name="arrow" size={18} /></a>
        </article>
      </div>
      <div className="follow-through">
        <div className="follow-through-icon"><Icon name="clock" size={30} /></div><div><span className="feature-number">03 / A little follow-through</span><h3>Good morning. Your brief is ready.</h3><p>Put useful work on a schedule. Daily research, a weekly review, or a recurring group check-in, with run history and notifications when the work finishes.</p></div><a className="circle-link" href="/features/#routines" aria-label="Explore scheduled tasks"><Icon name="arrow" size={25} /></a>
      </div>
    </section>

    <section className="team-section" aria-labelledby="team-heading"><div className="wrap">
      <div className="section-heading split-heading"><div><p className="eyebrow">Different talents. Your team.</p><h2 id="team-heading">There’s a little<br />someone for that.</h2></div><div><p>{bots.length} ready-made bots. {skills.length} reusable skills. Pick your starting lineup, then give each one its own instructions, tools, and personality.</p><a className="text-link" href="/library/">Meet the whole team <Icon name="arrow" size={18} /></a></div></div>
      <div className="team-lineup">{featured.map((bot, index) => <a href={`/library/#${bot.id}`} className="team-member" key={bot.id}><span className="team-index">{String(index + 1).padStart(2, '0')}</span><TimIcon color={bot.color} size={104} /><h3>{bot.name}</h3><p>{bot.tagline}</p><span className="team-member-link">Meet {bot.name === 'Research & Reports' ? 'your researcher' : bot.name} <Icon name="diagonal" size={16} /></span></a>)}</div>
      <div className="custom-team-note"><Icon name="spark" /><p><strong>Have a very particular way of doing things?</strong> Write your own skill, import one from GitHub, or ask Chief to help make it.</p><a href="/skills/">Explore skills <Icon name="arrow" size={16} /></a></div>
    </div></section>

    <section className="connections-section wrap" aria-labelledby="connections-heading">
      <div className="connections-copy"><p className="eyebrow">Less copying. More connecting.</p><h2 id="connections-heading">Your world,<br />within reach.</h2><p>Let the right bot find context in the accounts you already use. Prepare for a meeting, research a project, or draft that email with the relevant information close at hand.</p><a className="button button-light" href="/features/#connections">Explore the connections <Icon name="arrow" /></a><span className="connections-note"><Icon name="sliders" size={17} />You choose which accounts each bot can use.</span></div>
      <div className="connections-board"><div className="connection-tiles">{providers.map(([id, name]) => <div className="connection-tile" key={id}><img src={`/assets/providers/${id}.png`} width="36" height="36" alt="" loading="lazy" /><span>{name}</span></div>)}</div><div className="connection-bottom"><Icon name="link" size={22} /><p><strong>Your tools can come, too.</strong><span>Connect trusted MCP servers, including Home Assistant.</span></p></div><p className="connections-availability">Connections vary during beta. See the app for current availability.</p></div>
    </section>

    <section className="section native-section wrap" aria-labelledby="native-heading">
      <div className="section-heading split-heading"><div><p className="eyebrow">Made to come along</p><h2 id="native-heading">On your desk.<br /><em>Out in the world.</em></h2></div><p>One team, in two native Apple apps. Your conversations, context, files, and routines travel with you.</p></div>
      <div className="native-grid">
        <article className="native-card mac-card"><div className="native-label"><Icon name="laptop" /><span>HEYTIM FOR MAC</span></div><h3>A helping hand<br />on your Mac.</h3><p>Mac Operator can navigate websites and work with supported controls in authorized Mac apps. Give it access per bot, sign in to its browser yourself, and step in whenever you need to.</p><div className="native-bottom"><span><Icon name="shield" size={17} />Your permissions. Your pace.</span><a href="/features/#apple" aria-label="Explore Mac features"><Icon name="diagonal" /></a></div></article>
        <article className="native-card phone-card"><div className="native-label"><Icon name="phone" /><span>HEYTIM FOR IPHONE</span></div><h3>Good ideas don’t<br />wait for your desk.</h3><p>Dictate on device, pick up a conversation, and get a notification when work finishes. With your permission, Health Coach can turn Apple Health activity summaries into useful reflections.</p><div className="native-bottom"><span><Icon name="mic" size={17} />On-device voice transcription.</span><a href="/features/#apple" aria-label="Explore iPhone features"><Icon name="diagonal" /></a></div></article>
      </div>
      <a className="all-features-link" href="/features/">And there’s more: documents, images, meeting notes, custom skills, and bot email.<span>See everything HeyTim can do <Icon name="arrow" /></span></a>
    </section>

    <section className="trust-section wrap" aria-labelledby="trust-heading"><div><Icon name="shield" size={32} /><h2 id="trust-heading">Helpful by design.<br />Yours to control.</h2><a className="text-link" href="/features/#control">A closer look at the controls <Icon name="arrow" size={18} /></a></div><div className="trust-points"><article><h3>Private stays personal.</h3><p>Groups have their own memory. Your private memory and connected accounts aren’t handed to other members.</p></article><article><h3>You give the go-ahead.</h3><p>Choose each bot’s tools, approve interactive access, and revoke it in settings. On Mac, using your mouse or keyboard pauses computer use.</p></article><article><h3>Your context, your call.</h3><p>Inspect, edit, delete, or export your memories. Shared links can be revoked, and account deletion is available in the app.</p></article></div></section>

    <section className="faq-section section wrap" aria-labelledby="faq-heading"><div><p className="eyebrow">A few good questions</p><h2 id="faq-heading">Glad you asked.</h2></div><div className="faq-list">
      <details><summary>What exactly is HeyTim?<Icon name="plus" /></summary><p>HeyTim is a native iPhone and Mac app where you build a personal team of AI bots. Talk one-to-one, bring people and bots into a group, give your team reusable skills, and schedule work you want done again.</p></details>
      <details><summary>Do I have to build my own bots?<Icon name="plus" /></summary><p>No. Start with Chief and choose from {bots.length} ready-made bots. Each one comes with a focused way of working. You can change your copy’s name, instructions, skills, and tools whenever you like.</p></details>
      <details><summary>What can my team actually make?<Icon name="plus" /></summary><p>Research, plans, budgets, briefs, meeting notes, and drafts can arrive right in the conversation. Ask for a download when you need a PDF, Word document, spreadsheet, or presentation. Image-enabled bots can create images, memes, and YouTube thumbnails.</p></details>
      <details><summary>Can I use HeyTim with other people?<Icon name="plus" /></summary><p>Yes. Invite people into a group, add bots, and build shared context. You can talk as a group, ask Chief, or bring in the team. Tools follow ownership and approval checks, while private memory and account credentials stay separate.</p></details>
      <details><summary>How do I get access?<Icon name="plus" /></summary><p>HeyTim is currently in private beta with invitation-based accounts. iPhone builds are distributed through TestFlight; the Mac app is available as a direct download. <a href="/download/">Get the app or request beta access.</a></p></details>
    </div></section>
    <GetStarted />
  </main>;
}
