// This private extension page is not web-accessible. No page content, cookies,
// authentication headers, or browsing history are read or sent anywhere.
async function configure() {
  const display = location.hash.slice(1);
  if (!['mobile', 'desktop'].includes(display)) throw new Error('Invalid display');
  const chromeVersion = navigator.userAgent.match(/Chrome\/([\d.]+)/)?.[1] ?? '130.0.0.0';
  const userAgent = `Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${chromeVersion} Mobile Safari/537.36`;
  await chrome.declarativeNetRequest.updateDynamicRules({
    removeRuleIds: [1],
    addRules: display === 'mobile' ? [{
      id: 1, priority: 1,
      action: { type: 'modifyHeaders', requestHeaders: [
        { header: 'user-agent', operation: 'set', value: userAgent },
        { header: 'sec-ch-ua-mobile', operation: 'set', value: '?1' },
        { header: 'sec-ch-ua-platform', operation: 'set', value: '"Android"' },
      ] },
      condition: { regexFilter: '^https?://', resourceTypes: ['main_frame', 'sub_frame', 'xmlhttprequest'] },
    }] : [],
  });
  document.documentElement.dataset.display = display;
}
configure().catch(() => { document.documentElement.dataset.display = 'error'; });
