export type ScrollPosition = { offset: number; contentHeight: number; viewportHeight: number };

export function shouldFollowLatest(
  following: boolean,
  previous: ScrollPosition,
  current: ScrollPosition,
): boolean {
  const distance = Math.max(0, current.contentHeight - current.viewportHeight - current.offset);
  const movement = current.offset - previous.offset;
  const resized = current.contentHeight !== previous.contentHeight || current.viewportHeight !== previous.viewportHeight;
  // An upward scroll is an explicit request to read history, including near the bottom.
  if (movement < -1 && distance > 8) return false;
  // Reattach only when moving back down near the bottom. Content growth, polling,
  // and viewport changes alone must never override the reader's position.
  if (!resized && movement > 1 && distance <= 64) return true;
  return following;
}
