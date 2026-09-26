import { featureGroups, integrations } from '../feature-content';
import { Icon } from '../icon';
import { GetStarted } from '../site-chrome';

export function Features() {
  return <main id="main">
    <section className="features-hero wrap"><p className="eyebrow">The whole little toolkit</p><h1 className="page-title">So much more<br />than <em>“ask me anything.”</em></h1><p className="page-intro">A team that remembers, researches, creates, and comes back to the work. Here’s what you can put it to work on.</p><a className="text-link" href="/download/">Get to know HeyTim <Icon name="arrow" size={18} /></a></section>
    <div className="feature-directory wrap">
      <nav className="feature-nav" aria-label="Feature categories"><span>EXPLORE HEYTIM</span>{featureGroups.map((group) => <a href={`#${group.id}`} key={group.id}><Icon name={group.icon} size={17} />{group.label}</a>)}<a href="#connections"><Icon name="link" size={17} />Connections</a></nav>
      <div className="feature-sections">
        {featureGroups.map((group, index) => <section className="feature-group" id={group.id} key={group.id} aria-labelledby={`${group.id}-heading`}>
          <span className="feature-group-number">{String(index + 1).padStart(2, '0')} / {group.label}</span><h2 id={`${group.id}-heading`}>{group.title}</h2><p className="feature-group-intro">{group.intro}</p>
          <div className="feature-items">{group.items.map((item) => <article key={item.title}><h3>{item.title}</h3><p>{item.description}</p></article>)}</div>
        </section>)}
        <section className="feature-group integration-directory" id="connections" aria-labelledby="integrations-heading"><span className="feature-group-number">08 / Connections</span><h2 id="integrations-heading">Bring the right context along.</h2><p className="feature-group-intro">Connect accounts in the app, then assign each one to the bots that need it. Multiple accounts stay separate.</p>
          <div className="availability-note"><Icon name="sliders" /><p><strong>Availability during beta</strong>These integrations are supported in the product. The Connections screen shows which providers are currently enabled for your environment. Some require provider approval or additional setup.</p></div>
          <div className="integration-list">{integrations.map((provider) => <article key={provider.name}><div><h3>{provider.name}</h3><span>{provider.scope}</span></div><p>{provider.detail}</p></article>)}</div>
          <p className="integration-footnote">Custom MCP servers require a public HTTPS endpoint and a bearer token. Local-network, tokenless, and OAuth-only MCP servers are not currently supported.</p>
        </section>
      </div>
    </div>
    <GetStarted compact />
  </main>;
}
