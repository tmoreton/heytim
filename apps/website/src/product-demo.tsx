import { useState } from 'react';
import { TimIcon } from './tim-icon';
import { Icon, type IconName } from './icon';

const stories: { label: string; room: string; context: string; prompt: string; bot: string; color: string;
  reply: string; result: string; detail: string; icon: IconName; memory: string }[] = [
  {
    label: 'Plan a trip', room: 'The long weekend', context: '3 people · Chief + Trip Planner',
    prompt: 'Somewhere by the sea. Under $600 each. And remember, Sam doesn’t drive.',
    bot: 'Trip Planner', color: '#3984F6',
    reply: 'Let’s start with places we can reach by train. I’ll compare travel, stays, and a little room in the budget for the good stuff.',
    result: 'One weekend. Everyone considered.', detail: 'Shared plan · Travel options · Budget', icon: 'people',
    memory: 'Sam prefers travel without a car',
  },
  {
    label: 'Prep my day', room: 'Morning Brief', context: 'Your daily briefing',
    prompt: 'Every weekday at 7, bring me the news that matters for my work.',
    bot: 'Morning Brief', color: '#FFAA34',
    reply: 'A short brief, with sources and next steps. Add your priorities to my instructions and I’ll use them each morning.',
    result: 'A routine you can come back to.', detail: 'Weekdays · 7:00 AM · Your timezone', icon: 'clock',
    memory: 'Keep my brief short and source-linked',
  },
  {
    label: 'Make something', room: 'Research & Reports', context: 'Your research partner',
    prompt: 'Compare these three ideas. Find the evidence, then make a one-page brief I can share.',
    bot: 'Research & Reports', color: '#6C5CE7',
    reply: 'I’ll compare the tradeoffs, link the sources, and flag the open questions. Then I can turn the findings into a PDF.',
    result: 'Good thinking. Something to show for it.', detail: 'Research · Clear tradeoffs · Shareable PDF', icon: 'file',
    memory: 'Lead with the recommendation',
  },
];

export function ProductDemo() {
  const [selected, setSelected] = useState(0);
  const story = stories[selected];
  return <figure className="demo-stage">
    <div className="demo-sticker" aria-hidden="true">A little team.<br /><span>A big help.</span></div>
    <div className="demo-window">
      <div className="demo-toolbar"><span className="demo-dots" aria-hidden="true"><i /><i /><i /></span><span>HeyTim</span><Icon name="sliders" size={16} /></div>
      <div className="demo-content" id="demo-conversation" aria-live="polite" aria-atomic="true">
        <div className="demo-room"><TimIcon size={46} /><div><strong>{story.room}</strong><span>{story.context}</span></div></div>
        <div className="demo-message demo-person"><span>You</span><p>{story.prompt}</p></div>
        <div className="demo-bot"><TimIcon size={32} color={story.color} /><div><strong>{story.bot}</strong><p>{story.reply}</p></div></div>
        <div className="demo-result"><span className="demo-result-icon"><Icon name={story.icon} size={21} /></span><div><strong>{story.result}</strong><span>{story.detail}</span></div></div>
      </div>
      <div className="demo-memory"><Icon name="memory" size={16} /><span>{story.memory}</span><span className="demo-memory-label">Memory</span></div>
    </div>
    <div className="demo-picker" role="group" aria-label="Explore an example">
      {stories.map((item, index) => <button key={item.label} type="button" aria-pressed={selected === index}
        aria-controls="demo-conversation" onClick={() => setSelected(index)}>{item.label}</button>)}
    </div>
    <figcaption>Illustrative conversations. Your team makes them your own.</figcaption>
  </figure>;
}
