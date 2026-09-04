import type { Invitation, InviteKind } from '@/lib/types';

const pathForKind = (kind: InviteKind) =>
  kind === 'skill' ? '/skill/' : kind === 'group' ? '/group/' : '/share/';

const kindFromUrl = (url: string): InviteKind => {
  if (url.includes('/group/')) return 'group';
  if (url.includes('/skill/')) return 'skill';
  if (url.includes('kind=chat')) return 'chat';
  return 'bot';
};

export function invitationFromUrl(url: string | null): Invitation | undefined {
  if (!url) return undefined;

  let kind = kindFromUrl(url);
  let token = '';
  try {
    const parsed = new URL(url);
    const queryKind = parsed.searchParams.get('kind');
    if (queryKind === 'bot' || queryKind === 'chat' || queryKind === 'group' || queryKind === 'skill') {
      kind = queryKind;
    } else if (parsed.hostname === 'group' || parsed.pathname.includes('/group/')) {
      kind = 'group';
    } else if (parsed.hostname === 'skill' || parsed.pathname.includes('/skill/')) {
      kind = 'skill';
    }
    token =
      parsed.searchParams.get('token') ??
      (parsed.hostname === 'share' || parsed.hostname === 'skill' || parsed.hostname === 'group'
        ? parsed.pathname.replace(/^\//, '')
        : (parsed.pathname.split(pathForKind(kind))[1] ?? ''));
  } catch {
    token = url.split(pathForKind(kind))[1] ?? '';
  }

  token = token.split(/[?#]/)[0];
  return token ? { kind, token } : undefined;
}
