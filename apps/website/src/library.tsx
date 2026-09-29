import { useState, type CSSProperties } from 'react';
import catalog from '../../../catalog/catalog.json';
import { availableEntries, filterEntries, type Bot, type Skill } from './catalog';
import { TimIcon } from './tim-icon';
import { Icon } from './icon';

const available = availableEntries(catalog);

export function Library({ kind = 'skills' }: { kind?: 'bots' | 'skills' }) {
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('All');
  const entries: (Bot | Skill)[] = kind === 'bots' ? available.bots : available.skills;
  const categories = ['All', ...new Set(entries.map((entry) => entry.category).sort())];
  const visible = filterEntries(entries, query, category);
  return <main id="main">
    <section className="library-hero wrap">
      <div><p className="eyebrow">{kind === 'bots' ? `${entries.length} personalities. Plenty of possibilities.` : `${entries.length} good ways to get things done.`}</p>
      <h1 className="page-title">{kind === 'bots' ? <>Find your<br /><em>kind of team.</em></> : <>A little know-how.<br /><em>Ready to go.</em></>}</h1>
      <p className="page-intro">{kind === 'bots'
        ? 'The trip planner. The number person. The creative one. Start with a specialist, then make its skills, instructions, and tools your own.'
        : 'Skills are reusable instructions that teach a bot your way of working. Browse the reviewed collection, then add skills or make your own in the app.'}</p></div>
      <div className="library-mascots" aria-hidden="true"><TimIcon size={120} color={kind === 'bots' ? '#FFBC3B' : '#3984F6'} /><TimIcon size={92} color={kind === 'bots' ? '#3984F6' : '#E95383'} /><span>{kind === 'bots' ? 'YOUR NEXT GREAT COLLABORATION' : 'SMALL INSTRUCTIONS. BIG POSSIBILITIES.'}</span></div>
    </section>
    <section className="directory wrap" aria-label={`${kind} directory`}>
      <div className="directory-toolbar">
      <nav className="library-tabs" aria-label="Library">
        <a href="/library/" aria-current={kind === 'bots' ? 'page' : undefined}>Bots</a>
        <a href="/skills/" aria-current={kind === 'skills' ? 'page' : undefined}>Skills</a>
      </nav>
      <label className="search-label"><span className="sr-only">Search {kind}</span><Icon name="search" size={18} />
        <input className="search" type="search" value={query} onChange={(e) => setQuery(e.target.value)}
          placeholder={`Search ${kind}`} autoComplete="off" />
      </label></div>
      <div className="categories" role="group" aria-label="Categories">
        {categories.map((name) => <button className="category" key={name} aria-pressed={name === category}
          onClick={() => setCategory(name)}>{name}</button>)}
      </div>
      <p className="directory-count" role="status">{visible.length} {visible.length === 1 ? kind.slice(0, -1) : kind}{query || category !== 'All' ? ' found' : ' to make your own'}<span>Reviewed instructions. Your editable copy.</span></p>
      <div className="catalog-grid">
        {visible.map((item) => <article key={item.id} className="catalog-card" id={item.id}>
          <div className="card-top">
            <span className="card-mark" style={{ '--bot-color': item.color ?? '#FFBC3B' } as CSSProperties}>
              <TimIcon color={item.color ?? '#FFBC3B'} size={64} />
            </span>
            <span className="badge">{item.category}</span>
          </div>
          <h2>{item.name}</h2><p>{item.tagline ?? item.description}</p>
          <p className="reviewed">{item.author} · Version {item.version}</p>
          <div className="detail-list">{item.tags.map((tag) => <span className="detail" key={tag}>{tag}</span>)}</div>
          {'path' in item ? <a className="catalog-link" href={`/${item.path}`}>Read the skill <Icon name="arrow" size={18} /></a>
            : <a className="catalog-link" href="/download/">Make this bot yours <Icon name="arrow" size={18} /></a>}
        </article>)}
        {visible.length === 0 ? <div className="empty"><Icon name="search" size={32} /><h2>No teammates here. Yet.</h2><p>Try a different search or category.</p>
          <button className="button-secondary" onClick={() => { setQuery(''); setCategory('All'); }}>Clear filters</button></div> : null}
      </div>
      <div className="library-contribute"><div><h2>Your way of working belongs here, too.</h2><p>Make a private skill in HeyTim, or propose a bot or skill for the reviewed collection.</p></div><a className="text-link" href="/contribute/">Make a contribution <Icon name="arrow" size={18} /></a></div>
    </section>
  </main>;
}
