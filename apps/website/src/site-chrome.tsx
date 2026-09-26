import { useState } from 'react';
import { Icon } from './icon';

export function Header({ route }: { route: string }) {
  const [menuOpen, setMenuOpen] = useState(false);
  return <header className="site-header" onKeyDown={(event) => {
    if (event.key === 'Escape' && menuOpen) {
      setMenuOpen(false);
      document.getElementById('menu-toggle')?.focus();
    }
  }}>
    <a className="wordmark" href="/" aria-label="HeyTim home"><img src="/assets/tim-mark.svg" alt="" width="38" height="38" /><span>HeyTim<span className="wordmark-period">.</span></span></a>
    <button className="menu-toggle" id="menu-toggle" type="button" aria-expanded={menuOpen} aria-controls="main-nav"
      onClick={() => setMenuOpen(!menuOpen)}><span>{menuOpen ? 'Close' : 'Menu'}</span><Icon name={menuOpen ? 'close' : 'menu'} /></button>
    <nav className={`site-nav${menuOpen ? ' is-open' : ''}`} id="main-nav" aria-label="Main navigation" onClick={() => setMenuOpen(false)}>
      <a href="/features/" aria-current={route === '/features' ? 'page' : undefined}>What it can do</a>
      <a href="/library/" aria-current={route === '/library' || route === '/skills' ? 'page' : undefined}>Meet the team</a>
      <a href="/#how-it-works">How it works</a>
      <a className="button nav-cta" href="/download/" aria-current={route === '/download' ? 'page' : undefined}>Get HeyTim <Icon name="diagonal" size={17} /></a>
    </nav>
  </header>;
}

export function Footer() {
  return <footer className="site-footer">
    <div className="footer-top">
      <div className="footer-about"><a className="wordmark" href="/" aria-label="HeyTim home"><img src="/assets/tim-mark.svg" alt="" width="38" height="38" /><span>HeyTim.</span></a><p>A little team for your whole life.</p><span className="footer-beta">Made for iPhone & Mac · Private beta</span></div>
      <nav aria-label="Product"><h2>The good stuff</h2><a href="/features/">All features</a><a href="/library/">Meet the bots</a><a href="/skills/">Explore skills</a><a href="/download/">Get the app</a></nav>
      <nav aria-label="Community"><h2>Make it yours</h2><a href="/contribute/">Contribute</a><a href="https://github.com/tmoreton/heytim">View the source <Icon name="diagonal" size={13} /></a><a href="mailto:support@heytim.ai">Say hello</a></nav>
    </div>
    <div className="footer-bottom"><span>© 2026 HeyTim</span><nav aria-label="Legal"><a href="/privacy/">Privacy</a><a href="/terms/">Terms</a><a href="/sms/">SMS program</a></nav><span>Big on possibilities. Small on fuss.</span></div>
  </footer>;
}

export function GetStarted({ compact = false }: { compact?: boolean }) {
  return <section className={`get-started wrap${compact ? ' is-compact' : ''}`} aria-labelledby="get-started-heading">
    <div><p className="eyebrow">Meet your new favorite team</p><h2 id="get-started-heading">A little backup.<br />A lot more you.</h2><p>Bring your plans, projects, and people. We’ll bring the team.</p></div>
    <div className="get-started-action"><a className="button" href="/download/">Get HeyTim <Icon name="arrow" /></a><span>For iPhone and Mac. Access by invitation.</span></div>
  </section>;
}
