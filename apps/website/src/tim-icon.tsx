export function TimIcon({ color = '#FFBC3B', size = 48 }: { color?: string; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 100 100" aria-hidden="true" focusable="false">
    <path d="M50 21C50 11 56 7 65 7" fill="none" stroke="#252829" strokeWidth="8" strokeLinecap="round" />
    <circle cx="69" cy="8" r="8" fill={color} />
    <circle cx="69" cy="8" r="2.7" fill="#FFFDF8" />
    <circle cx="50" cy="58" r="39" fill={color} />
    <rect x="18" y="40" width="64" height="38" rx="19" fill="#252829" />
    <path d="M29 62c1-7 11-7 12 0m18 0c1-7 11-7 12 0" fill="none" stroke="#FFFDF8" strokeWidth="5.5" strokeLinecap="round" />
  </svg>;
}
