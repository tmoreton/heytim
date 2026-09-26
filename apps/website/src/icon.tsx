import type { CSSProperties } from 'react';

const paths = {
  arrow: 'M5 12h14m-6-6 6 6-6 6',
  diagonal: 'M6 18 18 6M6 6h12v12',
  check: 'm5 12 4 4L19 6',
  plus: 'M12 5v14M5 12h14',
  close: 'm6 6 12 12M6 18 18 6',
  menu: 'M4 7h16M4 12h16M4 17h16',
  clock: 'M12 8v4l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  file: 'M14 2H5v20h14V7l-5-5v6h5M8 12h8M8 16h6',
  memory: 'M9 4H7a3 3 0 0 0-3 3v2a3 3 0 0 0 0 6v2a3 3 0 0 0 3 3h2m6-16h2a3 3 0 0 1 3 3v2a3 3 0 0 1 0 6v2a3 3 0 0 1-3 3h-2M9 2v20M15 2v20M4 9h2m12 6h2',
  people: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m20 0v-2a4 4 0 0 0-3-3.87M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8m7 .13a4 4 0 0 1 0 7.75',
  sliders: 'M4 21v-7m0-4V3m8 18v-9m0-4V3m8 18v-5m0-4V3M1 10h6m2 2h6m2 4h6',
  link: 'm10 13 4-4m-7 6-1 1a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m2 4 1-1a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0',
  laptop: 'M4 3h16v13H4V3ZM2 20h20l-2-4H4l-2 4Z',
  phone: 'M7 2h10a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1Zm3 17h4M10 5h4',
  mic: 'M9 5a3 3 0 0 1 6 0v6a3 3 0 0 1-6 0V5Zm-3 6a6 6 0 0 0 12 0M12 17v5m-4 0h8',
  shield: 'm12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6l9-4Zm-4 10 3 3 5-6',
  search: 'M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  spark: 'm12 2 2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5L12 2Z',
  mail: 'M2 5h20v14H2V5Zm0 0 10 8L22 5',
  heart: 'M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z',
  globe: 'M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0ZM2 12h20M12 2a19 19 0 0 0 0 20 19 19 0 0 0 0-20Z',
} as const;

export type IconName = keyof typeof paths;

export function Icon({ name, size = 20, style }: { name: IconName; size?: number; style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={style}>
    <path d={paths[name]} />
  </svg>;
}
