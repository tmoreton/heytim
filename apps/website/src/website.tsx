import { Home } from './pages/home';
import { Privacy } from './pages/privacy';
import { Terms } from './pages/terms';
import { Sms } from './pages/sms';
import { Contribute } from './pages/contribute';
import { Library } from './library';
import { OpenApp } from './open-app';

export const pages: Record<string, string> = {
  '/': 'FroggyBot — Turn group talk into action',
  '/library': 'Ready-made bots — FroggyBot', '/skills': 'Skills — FroggyBot',
  '/privacy': 'Privacy Policy — FroggyBot', '/terms': 'Terms of Use — FroggyBot',
  '/sms': 'SMS program — FroggyBot', '/contribute': 'Contribute — FroggyBot',
  '/download': 'Get the Apple app — FroggyBot', '/app': 'Open FroggyBot',
  '/invite': 'You’re invited — FroggyBot',
};

export function Website({ pathname }: { pathname: string }) {
  const route = pathname.replace(/\/+$/, '') || '/';
  const content = route === '/' ? <Home />
    : route === '/library' ? <Library kind="bots" /> : route === '/skills' ? <Library />
    : route === '/privacy' ? <Privacy /> : route === '/terms' ? <Terms />
    : route === '/sms' ? <Sms /> : route === '/contribute' ? <Contribute />
    : route === '/invite' ? <OpenApp invite />
    : route === '/download' || route === '/app' ? <OpenApp />
    : <main className="doc-page" id="main"><h1>This page has hopped away.</h1><p>Try the skills library or return home.</p><a className="button" href="/">Back to home</a></main>;
  return <>
    <a className="skip-link" href="#main">Skip to content</a>
    <header className="site-header">
      <a className="wordmark" href="/" aria-label="FroggyBot home"><img src="/assets/frogbot.png" alt="" width="38" height="38" /><span>FroggyBot</span></a>
      <nav className="site-nav" aria-label="Main navigation">
        <a href="/library/" aria-current={route === '/library' ? 'page' : undefined}>Bots</a>
        <a href="/skills/" aria-current={route === '/skills' ? 'page' : undefined}>Skills</a>
        <a className="nav-optional" href="/contribute/">Contribute</a>
        <a className="button-secondary" href="/download/">Get the app</a>
      </nav>
    </header>
    {content}
    <footer className="site-footer"><span>© 2026 FroggyBot</span><nav className="footer-links" aria-label="Footer">
      <a href="/sms/">SMS program</a><a href="/privacy/">Privacy</a><a href="/terms/">Terms</a>
      <a href="/skills/">Skills</a><a href="mailto:tmoreton89@gmail.com">Contact</a>
    </nav></footer>
  </>;
}
