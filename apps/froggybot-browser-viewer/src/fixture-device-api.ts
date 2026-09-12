// Isolated browser UI fixture only: Expo native modules are unavailable here.
// Real link routing is exercised; unexpected external navigation fails loudly.
export async function openURL(_url: string) { throw new Error('Unexpected external navigation'); }
export async function setStringAsync(_value: string) { return true; }
