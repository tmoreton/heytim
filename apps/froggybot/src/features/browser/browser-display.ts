export const browserViewports = {
  mobile: { width: 390, height: 780 },
  desktop: { width: 1440, height: 900 },
} as const;

export function viewerViewport(value: unknown): { width: number; height: number } {
  if (value && typeof value === 'object' && 'width' in value && 'height' in value) {
    for (const viewport of Object.values(browserViewports)) {
      if (value.width === viewport.width && value.height === viewport.height) return viewport;
    }
  }
  // Backward compatible with existing API responses and already-open sessions.
  return browserViewports.desktop;
}
