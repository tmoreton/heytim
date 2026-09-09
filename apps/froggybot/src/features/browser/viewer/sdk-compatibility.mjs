/** Narrow, version-checked adjustments to AWS's Apache-licensed React wrapper.
 * The vendored DCV client is not modified. */
export function privateLiveViewSource(source) {
  const unsafe = "setDcvError(`Authentication error: ${error instanceof Error ? error.message : 'Unknown'}`)";
  const layout = /conn\.requestDisplayLayout\?\.\((\[[\s\S]*?\])\);/;
  const decoderBase = "baseUrl: '/nice-dcv-web-client-sdk/dcvjs-esm'";
  if (!source.includes(unsafe) || !source.includes('dcv.LogLevel.INFO') || !layout.test(source) || !source.includes(decoderBase)) {
    throw new Error('Review updated AWS viewer compatibility before building.');
  }
  return source.replace(unsafe, "setDcvError('Connection failed. Use Refresh connection.')")
    .replaceAll('dcv.LogLevel.INFO', 'dcv.LogLevel.SILENT')
    // DCV strips a leading slash and resolves a relative base against the page
    // directory. Our isolated /bot-browser/ viewer therefore needs an absolute
    // same-origin decoder URL, otherwise its video workers silently get 404s.
    .replace(decoderBase, "baseUrl: new URL('/nice-dcv-web-client-sdk/dcvjs-esm', window.location.origin).href")
    // Layout is advisory. AgentCore may not expose its display channel, and
    // requestDisplayLayout rejects asynchronously, beyond the SDK's try/catch.
    .replace(layout, 'Promise.resolve(conn.requestDisplayLayout?.($1)).catch(() => {});');
}
