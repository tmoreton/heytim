import type { IconName } from './icon';

type FeatureGroup = {
  id: string; label: string; title: string; intro: string; icon: IconName;
  items: { title: string; description: string }[];
};

export const featureGroups: FeatureGroup[] = [
  {
    id: 'team', label: 'Your team', title: 'Give each bot a job. Make it yours.', icon: 'spark',
    intro: 'Start with a specialist or build one around the way you work.',
    items: [
      { title: 'Chief, your coordinator', description: 'Start with Chief to plan work, coordinate the team, and help you create or adjust your bots and private skills in a direct conversation.' },
      { title: 'Ready-made specialists', description: 'Planning, research, budgets, data, social writing, career prep, health, creative work, and more. Every installed bot becomes your own editable copy.' },
      { title: 'Custom instructions and tools', description: 'Choose a bot’s name, personality, instructions, skills, tools, and account connections. You decide what each member of your team can do.' },
      { title: 'Reusable skills', description: 'Give bots a repeatable way of working with reviewed, versioned instructions. Write a private skill, ask a bot to help create one, or preview and import a public GitHub SKILL.md.' },
    ],
  },
  {
    id: 'memory', label: 'Memory & context', title: 'Pick up where you left off.', icon: 'memory',
    intro: 'Keep the useful context close, from small preferences to ongoing projects.',
    items: [
      { title: 'Personal memory', description: 'Your bots can recall preferences, useful facts, and summaries of earlier conversations. Review, edit, delete, and export remembered information in the app.' },
      { title: 'Shared group context', description: 'Give a group its own goals, background, and preferences. Group memory is separate from each member’s personal memory, with context the group owner can edit.' },
      { title: 'Files that stay with the work', description: 'Upload reference documents and images, keep files with a bot or group, and return to them in later work. File access follows the conversation’s ownership and membership.' },
      { title: 'Decisions worth keeping', description: 'Save a group decision with attribution so people and bots have something concrete to return to as the conversation moves on.' },
    ],
  },
  {
    id: 'together', label: 'People & groups', title: 'Bring everyone into the same conversation.', icon: 'people',
    intro: 'For the things that take more than one person, or more than one perspective.',
    items: [
      { title: 'Direct and group conversations', description: 'Work privately with a bot or invite people into a shared room. Choose people-only conversation, ask Chief, or bring in compatible specialists.' },
      { title: 'Coordinated team rounds', description: 'Chief scopes the question, specialists contribute, and Chief brings the findings together. Contributions stay attributed, so you can see who added what.' },
      { title: 'Invites and sharing', description: 'Share a group invitation or a reusable bot or skill. Shared links can expire or be revoked. Sharing a template does not share your account connections or credentials.' },
      { title: 'Clear boundaries for groups', description: 'Groups use their own shared files and memory. Interactive tools follow ownership and approval checks; another member cannot use a shared bot to gain access to your private actions.' },
    ],
  },
  {
    id: 'routines', label: 'Tasks & follow-through', title: 'Make useful work a regular thing.', icon: 'clock',
    intro: 'Set up the task, choose the timing, and come back to the results.',
    items: [
      { title: 'Scheduled tasks', description: 'Run bot or group tasks hourly, on weekdays, daily, weekly, or monthly in your chosen timezone. Pause, edit, delete, or run a task now. Scheduled work with interactive tools needs advance approval.' },
      { title: 'Event routines', description: 'Start group work when a room decision is saved or an issue opens in a connected GitHub repository. Preview the prompt, choose the trigger, and review the resulting runs.' },
      { title: 'Run history and notifications', description: 'See scheduled task progress, completed outputs, and failures. Native notifications bring you back when work finishes; the scheduled time is when work starts.' },
      { title: 'Longer research and analysis', description: 'Bots can break work into steps, keep a working checklist, delegate focused research, and run code in an isolated workspace. Background jobs can resume in the same conversation.' },
      { title: 'A bot with an inbox', description: 'Where enabled, give a bot its own email address. Review incoming messages or allow authenticated mail from your verified address into its conversation. Choose app or email delivery for responses.' },
    ],
  },
  {
    id: 'create', label: 'Research & creation', title: 'Walk away with something useful.', icon: 'file',
    intro: 'From a clear answer in chat to a file you can put to work.',
    items: [
      { title: 'Research with sources', description: 'Search the web, read pages, compare evidence, and work through tradeoffs. Connected YouTube and X accounts add their own research tools when assigned to a bot.' },
      { title: 'Documents and data', description: 'Analyze uploaded data, calculate results, and make charts. Ask for downloadable PDFs, Word documents, Excel spreadsheets, PowerPoint decks, Markdown, CSV, JSON, or HTML.' },
      { title: 'Images, thumbnails, and memes', description: 'Image-enabled bots create original artwork and reference-aware YouTube thumbnails. Meme Lord captions familiar templates or an image you supply in the same chat.' },
      { title: 'Meeting notes and your own voice', description: 'Turn a supplied or on-device transcript into notes, summaries, decisions, and follow-ups. Build custom skills for your writing voice, research process, or recurring deliverables.' },
    ],
  },
  {
    id: 'apple', label: 'iPhone & Mac', title: 'A native app. A familiar place for your team.', icon: 'laptop',
    intro: 'Shared conversations and capabilities that make sense on each device.',
    items: [
      { title: 'One team across your devices', description: 'Use the native SwiftUI app on iPhone and Mac with the same account, bots, groups, schedules, files, and connections. Receive notifications and follow invitations into the app.' },
      { title: 'On-device dictation', description: 'Transcribe your voice on your device, then review and send the text to your bot. Longer meeting transcripts can be attached as a text file for notes and follow-ups.' },
      { title: 'Mac app actions and browser handoff', description: 'With per-bot permission, Mac Operator can use supported controls in authorized Mac apps. For websites, use its interactive browser and private sign-in handoff. Local input pauses Mac control until you resume it.' },
      { title: 'Apple Health on iPhone', description: 'Grant Health Coach read-only access to activity, workout, running, and step summaries. You choose the bot and Apple Health permissions; the tool does not request routes, clinical records, or write access.' },
    ],
  },
  {
    id: 'control', label: 'Your controls', title: 'Helpful has to feel comfortable.', icon: 'shield',
    intro: 'Know what is shared, what is connected, and what your team can do.',
    items: [
      { title: 'Access assigned per bot', description: 'Connecting an account does not grant it to every bot. Select each connection separately, narrow supported resources, and change those choices in settings.' },
      { title: 'Permission for interactive tools', description: 'Interactive tools ask for approval covering the bot’s enabled tools. You can revoke persistent approval. Device tools also require local permission on the authorized device.' },
      { title: 'Private and shared spaces', description: 'Personal chats, private files, group memory, and group files have separate access boundaries. Current group members can access the files shared with their group.' },
      { title: 'Portable context and visible source', description: 'Export memory, remove remembered information, revoke sharing links, or delete your account. HeyTim’s source is available under the PolyForm Noncommercial license.' },
      { title: 'Usage and plan', description: 'See your plan, work credits used, remaining credits, and renewal information in settings. Where available, manage a Plus subscription through the app’s billing flow.' },
    ],
  },
];

export const integrations = [
  { name: 'Gmail', detail: 'Search email, read threads, and create drafts for review.', scope: 'Read & draft' },
  { name: 'Google Workspace', detail: 'Read Drive files, Docs, Sheets, and Calendar events.', scope: 'Read only' },
  { name: 'Slack', detail: 'Search messages and read threads in selected workspaces.', scope: 'Read only' },
  { name: 'GitHub', detail: 'Work with selected repositories, branches, and pull requests.', scope: 'Selected repositories' },
  { name: 'YouTube', detail: 'Search videos and read connected channel details and uploads.', scope: 'Read only' },
  { name: 'X', detail: 'Search recent posts and read profiles, posts, and mentions.', scope: 'Read only' },
  { name: 'Notion', detail: 'Read shared pages and their content, with optional page limits.', scope: 'Read only' },
  { name: 'Microsoft 365', detail: 'Read Outlook mail and calendars; search OneDrive and SharePoint.', scope: 'Read only' },
  { name: 'Microsoft Teams', detail: 'Read joined teams, channels, and channel messages.', scope: 'Read only' },
  { name: 'HubSpot', detail: 'Search contacts, companies, and deals in an assigned account.', scope: 'Read only' },
  { name: 'Jira', detail: 'List projects and read issues, with optional project limits.', scope: 'Read only' },
  { name: 'Zoom', detail: 'List and read meetings from a connected account.', scope: 'Read only' },
  { name: 'QuickBooks Online', detail: 'Read reports, accounts, invoices, bills, and vendors.', scope: 'Read only' },
  { name: 'Plaid', detail: 'Read selected balances, transactions, and supported liabilities.', scope: 'Read only' },
  { name: 'MCP servers & Home Assistant', detail: 'Assign a trusted remote HTTPS server and its tools to specific bots. Home Assistant uses its Assist MCP endpoint.', scope: 'Server-defined tools' },
];
