import { useSyncExternalStore } from 'react';

const query = '(max-width: 719px)';

const subscribe = (onChange: () => void) => {
  const mediaQuery = window.matchMedia(query);
  mediaQuery.addEventListener('change', onChange);
  return () => mediaQuery.removeEventListener('change', onChange);
};

const getSnapshot = () => window.matchMedia(query).matches;
const getServerSnapshot = () => false;

export const useNarrowLayout = () =>
  useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
