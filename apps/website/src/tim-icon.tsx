function usesDarkInk(color: string): boolean {
  const hex = /^#([0-9a-f]{6})$/i.exec(color)?.[1];
  if (!hex) return true;
  const [red, green, blue] = [0, 2, 4].map((offset) => {
    const value = parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue > 0.179;
}

export function TimIcon({ color = '#FFBC3B', size = 48 }: { color?: string; size?: number }) {
  const darkInk = usesDarkInk(color);
  const faceInk = darkInk ? '#252829' : '#FFFDF8';
  const eyeInk = darkInk ? '#FFFDF8' : '#252829';
  return <svg width={size} height={size} viewBox="0 0 100 100" aria-hidden="true" focusable="false">
    <path d="M50 21C50 11 56 7 65 7" fill="none" stroke="currentColor" strokeWidth="8" strokeLinecap="round" />
    <circle cx="69" cy="8" r="8" fill={color} />
    <circle cx="69" cy="8" r="2.7" fill={eyeInk} />
    <circle cx="50" cy="58" r="39" fill={color} />
    <rect x="18" y="40" width="64" height="38" rx="19" fill={faceInk} />
    <path d="M29 62c1-7 11-7 12 0m18 0c1-7 11-7 12 0" fill="none" stroke={eyeInk} strokeWidth="5.5" strokeLinecap="round" />
  </svg>;
}
