import catalog from '../../../../catalog/catalog.json';
import { availableEntries } from '../catalog';
const botCount = availableEntries(catalog).bots.length;

export function Home() {
  return (<main id="main">
    <section className="hero">
      <div className="hero-copy">
        <p className="eyebrow">AI for real groups</p>
        <h1>Turn group talk into a plan everyone can use.</h1>
        <p>Invite people with one link, keep the group’s context editable, and let trusted AI specialists turn decisions into itineraries, budgets, checklists, PDFs, and more.</p>
        <div className="hero-actions">
          <a className="button" href="mailto:tmoreton89@gmail.com?subject=FroggyBot%20beta%20access">Request beta access <span aria-hidden="true">→</span></a>
          <a className="button-secondary" href="/download/">Get the Apple app</a>
          <a className="button-secondary" href="/library/">Browse ready-made bots</a>
        </div>
        <p className="beta-note"><strong>Private beta.</strong> Available for iPhone and Mac through TestFlight.</p>
      </div>
      <div className="product-window" aria-label="Example of a FroggyBot group conversation">
        <div className="window-bar"><span className="window-dots"><i></i><i></i><i></i></span><strong>FroggyBot</strong><span className="window-status">GROUP MEMORY ON</span></div>
        <div className="conversation">
          <div className="group-name"><img src="/assets/frogbot.png" alt="" /><span><strong>Weekend in Portland</strong><small>2 people · 3 specialists</small></span></div>
          <div className="message"><small>Research</small>Portland fits the train time, walkability, and vegetarian-food constraints.</div>
          <div className="message person"><small>Jordan</small>Choose it, keep us under $1,200, and get us home by 6.</div>
          <div className="outputs">
            <div className="output"><strong>Portland plan.pdf</strong><span>Itinerary + working budget</span></div>
            <div className="output"><strong>Decision saved</strong><span>From Chief · accepted by Taylor</span></div>
          </div>
        </div>
      </div>
    </section>

    <section className="proof-strip" id="why" aria-label="What makes FroggyBot different">
      <div className="proof-grid">
        <article className="proof"><b>01</b><h2>Group memory</h2><p>Goals, preferences, and decisions stay visible and owner-editable.</p></article>
        <article className="proof"><b>02</b><h2>One-link invites</h2><p>People can join with one clean link and no password to remember.</p></article>
        <article className="proof"><b>03</b><h2>Useful outputs</h2><p>Turn the conversation into plans, budgets, lists, PDFs, and spreadsheets.</p></article>
        <article className="proof"><b>04</b><h2>Ready-made team</h2><p>Choose specialists for planning, research, budgets, decisions, and more.</p></article>
      </div>
    </section>

    <section className="section">
      <div className="section-heading">
        <p className="eyebrow">From conversation to outcome</p>
        <h2>Everyone contributes. FroggyBot keeps it moving.</h2>
        <p>The group stays in control while its AI teammates organize context, surface tradeoffs, and turn the final decision into something reusable.</p>
      </div>
      <div className="steps">
        <article className="step"><span className="step-number">1</span><h3>Bring the people in</h3><p>Share one invite. Participants land directly in the group with the right context.</p></article>
        <article className="step"><span className="step-number">2</span><h3>Decide together</h3><p>FroggyBots compare preferences and options without taking over the conversation.</p></article>
        <article className="step"><span className="step-number">3</span><h3>Leave with the work done</h3><p>Automatically create the itinerary, budget, checklist, brief, or file the group needs.</p></article>
      </div>
    </section>

    <section className="library-callout">
      <div>
        <p className="eyebrow">Built in the open</p>
        <h2><span>{botCount}</span> ready-made bots. Build the team you need.</h2>
        <p>Each bot arrives with a focused way of working and the capabilities it needs. Add one in a click, then customize your copy.</p>
      </div>
      <div className="library-actions">
        <a className="button" href="/library/">Meet the bots</a>
        <a className="text-link" href="/contribute/">How to contribute →</a>
      </div>
    </section>
  </main>);
}
