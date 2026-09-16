import { useState, type CSSProperties } from 'react';
import catalog from '../../../catalog/catalog.json';
import { availableEntries, filterEntries, type Bot, type Skill } from './catalog';

const available = availableEntries(catalog);

export function Library({ kind = 'skills' }: { kind?: 'bots' | 'skills' }) {
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('All');
  const entries: (Bot | Skill)[] = kind === 'bots' ? available.bots : available.skills;
  const categories = ['All', ...new Set(entries.map((entry) => entry.category).sort())];
  const visible = filterEntries(entries, query, category);
  return <main id="main">
    <section className="library-hero">
      <p className="eyebrow">Built for useful work</p>
      <h1 className="page-title">{kind === 'bots' ? 'Meet your ready-made team.' : 'Good ways of working, ready to use.'}</h1>
      <p className="page-intro">{kind === 'bots'
        ? 'Start with a specialist, then customize its skills and prompt in the Apple app.'
        : 'Explore the reviewed instructions that give your bots a focused way to plan, research, create, and follow through.'}</p>
      <nav className="library-tabs" aria-label="Library">
        <a href="/library/" aria-current={kind === 'bots' ? 'page' : undefined}>Bots</a>
        <a href="/skills/" aria-current={kind === 'skills' ? 'page' : undefined}>Skills</a>
      </nav>
    </section>
    <section className="directory" aria-label={`${kind} directory`}>
      <label className="search-label">Search {kind}
        <input className="search" type="search" value={query} onChange={(e) => setQuery(e.target.value)}
          placeholder={`Search ${kind}`} autoComplete="off" />
      </label>
      <div className="categories" role="group" aria-label="Categories">
        {categories.map((name) => <button className="category" key={name} aria-pressed={name === category}
          onClick={() => setCategory(name)}>{name}</button>)}
      </div>
      <p className="directory-count" role="status">{visible.length} {kind}</p>
      <div className="catalog-grid">
        {visible.map((item) => <article key={item.id} className="catalog-card">
          <div className="card-top">
            <span className="card-mark" style={{ '--bot-color': item.color ?? '#007a3d' } as CSSProperties}>
              <img src="/assets/favicon.png" alt="" width="48" height="48" />
            </span>
            <span className="badge">{item.category}</span>
          </div>
          <h2>{item.name}</h2><p>{item.tagline ?? item.description}</p>
          <p className="reviewed">Reviewed · {item.author} · Version {item.version}</p>
          <div className="detail-list">{item.tags.map((tag) => <span className="detail" key={tag}>{tag}</span>)}</div>
          {'path' in item ? <a className="button" href={`/${item.path}`}>Read skill instructions <span aria-hidden="true">→</span></a>
            : <a className="button" href="/download/">Use in FroggyBot <span aria-hidden="true">→</span></a>}
        </article>)}
        {visible.length === 0 ? <p className="empty">No matches. Try a different search or category.
          <button className="text-button" onClick={() => { setQuery(''); setCategory('All'); }}>Clear filters</button></p> : null}
      </div>
    </section>
  </main>;
}
