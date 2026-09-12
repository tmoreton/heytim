import { useMemo, useSyncExternalStore } from 'react';
import { useLocalSearchParams } from 'expo-router';

import { InviteScreen } from '@/features/invites/invite-screen';
import { invitationFromParams } from '@froggybot/client';

const subscribeToHydration = () => () => {};
const getClientSnapshot = () => true;
const getServerSnapshot = () => false;

export default function InvitePage() {
  const params = useLocalSearchParams<{ kind?: string | string[]; token?: string | string[] }>();
  const hydrated = useSyncExternalStore(subscribeToHydration, getClientSnapshot, getServerSnapshot);
  const invitation = useMemo(
    () => hydrated ? invitationFromParams(params.kind, params.token) : undefined,
    [hydrated, params.kind, params.token],
  );

  return <InviteScreen hydrated={hydrated} invitation={invitation} />;
}
