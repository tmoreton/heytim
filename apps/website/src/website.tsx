import { Home } from './pages/home';
import { Privacy } from './pages/privacy';
import { Terms } from './pages/terms';
import { Sms } from './pages/sms';
import { Contribute } from './pages/contribute';
import { BillingReturn } from './pages/billing';
import { Library } from './library';
import { OpenApp } from './open-app';
import { normalizePathname } from './route';
import { Features } from './pages/features';
import { Header, Footer } from './site-chrome';

export const pages: Record<string, string> = {
  '/': 'HeyTim — A little team for your whole life',
  '/features': 'What HeyTim can do — Features & connections',
  '/library': 'Ready-made bots — HeyTim', '/skills': 'Skills — HeyTim',
  '/privacy': 'Privacy Policy — HeyTim', '/terms': 'Terms of Use — HeyTim',
  '/sms': 'SMS program — HeyTim', '/contribute': 'Contribute — HeyTim',
  '/download': 'Get the Apple app — HeyTim', '/app': 'Open HeyTim',
  '/invite': 'You’re invited — HeyTim',
  '/billing': 'Return to HeyTim — Billing',
};

export function Website({ pathname }: { pathname: string }) {
  const route = normalizePathname(pathname);
  const content = route === '/' ? <Home />
    : route === '/features' ? <Features />
    : route === '/library' ? <Library kind="bots" /> : route === '/skills' ? <Library />
    : route === '/privacy' ? <Privacy /> : route === '/terms' ? <Terms />
    : route === '/sms' ? <Sms /> : route === '/contribute' ? <Contribute />
    : route === '/invite' ? <OpenApp invite />
    : route === '/billing' ? <BillingReturn />
    : route === '/download' || route === '/app' ? <OpenApp />
    : <main className="doc-page" id="main"><h1>We couldn’t find that page.</h1><p>Try the skills library or return home.</p><a className="button" href="/">Back to home</a></main>;
  return <>
    <a className="skip-link" href="#main">Skip to content</a>
    <Header route={route} />
    {content}
    <Footer />
  </>;
}
