import type { Invitation, InviteKind } from '@/lib/types';

const INVITE_KINDS = new Set<InviteKind>(['bot', 'chat', 'group', 'skill']);
const isInviteKind = (value: string | undefined): value is InviteKind =>
  Boolean(value && INVITE_KINDS.has(value as InviteKind));

export function firstRouteParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

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

export function invitationFromParams(
  kindParam: string | string[] | undefined,
  tokenParam: string | string[] | undefined,
): Invitation | undefined {
  const kind = firstRouteParam(kindParam);
  const token = firstRouteParam(tokenParam);
  return isInviteKind(kind) && token ? { kind, token } : undefined;
}

export function invitationUrl(invitation: Invitation): string {
  return `frogbot://invite?kind=${invitation.kind}&token=${encodeURIComponent(invitation.token)}`;
}
