import { useState } from 'react';
import * as Linking from 'expo-linking';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { PageSheet } from '@/components/page-sheet';
import type { Capability, Connection, ConnectionProvider } from '@/lib/types';

import { capabilityAccessLabel, userConnections } from './connection-access';

type Props = {
  tools: Capability[];
  providers: ConnectionProvider[];
  onClose: () => void;
  onBeginConnection: (providerId: string, returnUrl: string) => Promise<string>;
  onDeleteConnection: (connectionId: string) => Promise<void>;
  onChanged: () => Promise<void>;
};

function ConnectionDetails({
  connection,
  provider,
  busy,
  onReconnect,
  onRemove,
}: {
  connection: Connection;
  provider?: ConnectionProvider;
  busy: boolean;
  onReconnect?: () => void;
  onRemove: () => void;
}) {
  const oauth = connection.authType === 'oauth';
  return (
    <>
      <View style={[styles.detailCard, oauth ? styles.connectedCard : styles.legacyCard]}>
        <Text style={[styles.detailStatus, !oauth && styles.legacyStatus]}>
          {capabilityAccessLabel(connection)}
        </Text>
        <Text style={styles.detailName}>{connection.name}</Text>
        {connection.connectedAccount ? (
          <Text style={styles.account}>{connection.connectedAccount}</Text>
        ) : null}
        <Text style={styles.description}>{connection.description}</Text>
      </View>

      {oauth ? (
        <View style={styles.notice}>
          <Text style={styles.noticeTitle}>{provider?.privacyTitle ?? 'Your account stays private'}</Text>
          <Text style={styles.noticeText}>
            {provider?.privacyDescription ?? 'FroggyBot uses this connection only when a bot needs the account.'}
          </Text>
        </View>
      ) : (
        <View style={styles.notice}>
          <Text style={styles.noticeTitle}>Existing connection</Text>
          <Text style={styles.noticeText}>
            This earlier private connection remains available to bots that already use it. You can remove it, but
            cannot change its endpoint or developer credential. New supported services use Connect account.
          </Text>
          <Text selectable style={styles.endpoint}>{connection.endpoint}</Text>
          <Text style={styles.accessLevel}>
            {connection.risk === 'read' ? 'Read only' : 'Can make changes with approval'}
          </Text>
        </View>
      )}

      {onReconnect ? (
        <Pressable
          accessibilityRole="button"
          accessibilityState={{ busy, disabled: busy }}
          disabled={busy}
          style={({ pressed }) => [styles.primaryButton, pressed && styles.pressed]}
          onPress={onReconnect}>
          {busy ? (
            <ActivityIndicator color="#FFFFFF" />
          ) : (
            <Text style={styles.primaryButtonText}>Reconnect account</Text>
          )}
        </Pressable>
      ) : null}
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ busy, disabled: busy }}
        disabled={busy}
        style={({ pressed }) => [styles.removeButton, pressed && styles.pressed]}
        onPress={onRemove}>
        <Text style={styles.removeButtonText}>Remove connection</Text>
      </Pressable>
    </>
  );
}

function ConnectionRow({
  connection,
  onPress,
}: {
  connection: Connection;
  onPress: () => void;
}) {
  const label = capabilityAccessLabel(connection);
  return (
    <Pressable
      accessibilityRole="button"
      style={({ pressed }) => [styles.card, pressed && styles.pressed]}
      onPress={onPress}>
      <View style={styles.connectionMark}><Text style={styles.connectionMarkText}>C</Text></View>
      <View style={styles.cardText}>
        <View style={styles.nameRow}>
          <Text style={styles.cardName}>{connection.name}</Text>
          <Text style={[styles.badge, label === 'Connected' ? styles.connectedBadge : styles.legacyBadge]}>
            {label}
          </Text>
        </View>
        <Text style={styles.description}>{connection.description}</Text>
        <Text style={styles.meta}>
          {connection.connectedAccount ?? 'Available to existing bots'}
        </Text>
      </View>
      <Text style={styles.chevron}>›</Text>
    </Pressable>
  );
}

export function Connections({
  tools,
  providers,
  onClose,
  onBeginConnection,
  onDeleteConnection,
  onChanged,
}: Props) {
  const [selectedId, setSelectedId] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const connections = userConnections(tools);
  const selected = connections.find((connection) => connection.id === selectedId);
  const providersById = new Map(providers.map((provider) => [provider.id, provider]));
  const connectionsByProvider = new Map(
    connections.flatMap((connection) => connection.provider ? [[connection.provider, connection] as const] : []),
  );
  const selectedProvider = selected?.provider ? providersById.get(selected.provider) : undefined;
  const unmanagedOAuth = connections.filter(
    (connection) => connection.authType === 'oauth' && !providersById.has(connection.provider ?? ''),
  );
  const legacy = connections.filter((connection) => connection.authType !== 'oauth');

  const connect = async (provider: ConnectionProvider) => {
    setBusy(true);
    setError('');
    try {
      const returnUrl = Linking.createURL('app', { queryParams: { connection: provider.id } });
      const authorizationUrl = await onBeginConnection(provider.id, returnUrl);
      await Linking.openURL(authorizationUrl);
    } catch (value) {
      setError(value instanceof Error ? value.message : `Could not connect ${provider.name}.`);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (connection: Connection) => {
    setBusy(true);
    setError('');
    try {
      await onDeleteConnection(connection.id);
      await onChanged();
      setSelectedId(undefined);
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not remove this connection.');
    } finally {
      setBusy(false);
    }
  };

  const confirmRemove = (connection: Connection) => {
    Alert.alert(
      'Remove connection?',
      'Remove it from any bots or skills that use it first. FroggyBot will request provider revocation, remove local access either way, and place the saved credential in a seven-day deletion window.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Remove',
          style: 'destructive',
          onPress: () => void remove(connection),
        },
      ],
    );
  };

  const closeOrBack = () => {
    setError('');
    if (selected) setSelectedId(undefined);
    else onClose();
  };

  return (
    <PageSheet accessibilityLabel="Connections" onClose={onClose}>
      <View style={styles.page}>
        <View style={styles.header}>
          <Pressable accessibilityRole="button" hitSlop={12} onPress={closeOrBack}>
            <Text style={styles.headerAction}>{selected ? 'Back' : 'Close'}</Text>
          </Pressable>
          <Text accessibilityRole="header" numberOfLines={1} style={styles.title}>
            {selected?.name ?? 'Connections'}
          </Text>
          <View style={styles.headerSpacer} />
        </View>
        <ScrollView contentContainerStyle={styles.content}>
          {selected ? (
            <ConnectionDetails
              connection={selected}
              provider={selectedProvider}
              busy={busy}
              onReconnect={selectedProvider ? () => void connect(selectedProvider) : undefined}
              onRemove={() => confirmRemove(selected)}
            />
          ) : (
            <>
              <View style={styles.intro}>
                <Text style={styles.introTitle}>Connect accounts, not developer keys</Text>
                <Text style={styles.introText}>
                  Public research and creation tools are included. Sign in only when a bot needs access to your private
                  account data.
                </Text>
              </View>

              <Text style={styles.sectionLabel}>Available accounts</Text>
              {providers.map((provider) => {
                const connection = connectionsByProvider.get(provider.id);
                if (connection) {
                  return (
                    <ConnectionRow
                      key={provider.id}
                      connection={connection}
                      onPress={() => setSelectedId(connection.id)}
                    />
                  );
                }
                return (
                  <Pressable
                    accessibilityRole="button"
                    accessibilityState={{ busy, disabled: busy }}
                    disabled={busy}
                    key={provider.id}
                    style={({ pressed }) => [styles.card, styles.connectCard, pressed && styles.pressed]}
                    onPress={() => void connect(provider)}>
                    <View style={styles.providerMark}>
                      <Text style={styles.providerMarkText}>{provider.iconText}</Text>
                    </View>
                    <View style={styles.cardText}>
                      <View style={styles.nameRow}>
                        <Text style={styles.cardName}>{provider.name}</Text>
                        <Text style={[styles.badge, styles.connectBadge]}>Connect account</Text>
                      </View>
                      <Text style={styles.description}>{provider.description}</Text>
                      <Text style={styles.meta}>{provider.permissionsSummary}</Text>
                    </View>
                    {busy ? <ActivityIndicator color="#007A3D" /> : <Text style={styles.chevron}>›</Text>}
                  </Pressable>
                );
              })}
              {unmanagedOAuth.map((connection) => (
                <ConnectionRow
                  key={connection.id}
                  connection={connection}
                  onPress={() => setSelectedId(connection.id)}
                />
              ))}

              {legacy.length ? (
                <>
                  <Text style={styles.sectionLabel}>Existing private connections</Text>
                  <Text style={styles.sectionHelp}>
                    These remain available to existing bots. They are read-only here and can be removed when no bot or
                    skill uses them.
                  </Text>
                  {legacy.map((connection) => (
                    <ConnectionRow
                      key={connection.id}
                      connection={connection}
                      onPress={() => setSelectedId(connection.id)}
                    />
                  ))}
                </>
              ) : null}
            </>
          )}
          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
        </ScrollView>
      </View>
    </PageSheet>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: '#F8F7F3' },
  header: { minHeight: 58, paddingHorizontal: 18, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: '#DDDAD2', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: '#FBFBF9' },
  headerAction: { width: 58, color: '#44413B', fontSize: 15, fontWeight: '600' },
  headerSpacer: { width: 58 },
  title: { maxWidth: '66%', color: '#171714', fontSize: 16, fontWeight: '700' },
  content: { width: '100%', maxWidth: 680, alignSelf: 'center', padding: 20, paddingBottom: 60 },
  intro: { padding: 18, borderRadius: 18, backgroundColor: '#E9F4EE', marginBottom: 24 },
  introTitle: { color: '#173E2A', fontSize: 18, lineHeight: 24, fontWeight: '800' },
  introText: { color: '#527060', fontSize: 13, lineHeight: 19, marginTop: 5 },
  sectionLabel: { color: '#24231F', fontSize: 13, fontWeight: '800', marginTop: 8, marginBottom: 10, textTransform: 'uppercase', letterSpacing: 0.7 },
  sectionHelp: { color: '#6E6A62', fontSize: 13, lineHeight: 19, marginTop: -4, marginBottom: 12 },
  card: { minHeight: 84, flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, marginBottom: 10, borderRadius: 17, borderWidth: 1, borderColor: '#E2DFD7', backgroundColor: '#FFFFFF' },
  connectCard: { borderColor: '#CBE2D5', backgroundColor: '#F3FAF6' },
  providerMark: { width: 44, height: 44, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: '#DCEFE4' },
  providerMarkText: { color: '#007A3D', fontSize: 18, fontWeight: '900' },
  connectionMark: { width: 44, height: 44, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: '#EFEEE9' },
  connectionMarkText: { color: '#57534C', fontSize: 17, fontWeight: '900' },
  cardText: { flex: 1, minWidth: 0 },
  nameRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8 },
  cardName: { flexShrink: 1, color: '#24231F', fontSize: 15, fontWeight: '700' },
  badge: { overflow: 'hidden', borderRadius: 8, paddingHorizontal: 7, paddingVertical: 3, fontSize: 10, fontWeight: '800' },
  connectBadge: { color: '#007A3D', backgroundColor: '#DCEFE4' },
  connectedBadge: { color: '#007A3D', backgroundColor: '#E4F1EA' },
  legacyBadge: { color: '#6E5A26', backgroundColor: '#F6EDD2' },
  description: { color: '#6E6A62', fontSize: 12, lineHeight: 17, marginTop: 4 },
  meta: { color: '#6E6A62', fontSize: 11, marginTop: 5 },
  chevron: { color: '#6E6A62', fontSize: 25, fontWeight: '300' },
  detailCard: { padding: 18, borderRadius: 18, borderWidth: 1, marginBottom: 12 },
  connectedCard: { borderColor: '#CBE2D5', backgroundColor: '#E9F4EE' },
  legacyCard: { borderColor: '#E6D6A8', backgroundColor: '#FFF9E8' },
  detailStatus: { color: '#007A3D', fontSize: 11, fontWeight: '800', textTransform: 'uppercase', letterSpacing: 0.6 },
  legacyStatus: { color: '#6E5A26' },
  detailName: { color: '#173E2A', fontSize: 18, fontWeight: '800', marginTop: 6 },
  account: { color: '#007A3D', fontSize: 14, fontWeight: '700', marginTop: 5 },
  notice: { padding: 16, borderRadius: 17, borderWidth: 1, borderColor: '#DEDAD2', backgroundColor: '#FFFFFF' },
  noticeTitle: { color: '#37352F', fontSize: 15, fontWeight: '800' },
  noticeText: { color: '#6E6A62', fontSize: 13, lineHeight: 19, marginTop: 5 },
  endpoint: { color: '#4F4C46', fontSize: 12, lineHeight: 18, marginTop: 14 },
  accessLevel: { color: '#6E5A26', fontSize: 12, fontWeight: '700', marginTop: 8 },
  primaryButton: { minHeight: 47, marginTop: 24, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: '#007A3D' },
  primaryButtonText: { color: '#FFFFFF', fontSize: 14, fontWeight: '800' },
  removeButton: { minHeight: 47, marginTop: 12, borderRadius: 14, borderWidth: 1, borderColor: '#E2B9B4', alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFF8F7' },
  removeButtonText: { color: '#A53A32', fontSize: 14, fontWeight: '700' },
  error: { color: '#A43C31', fontSize: 13, lineHeight: 18, marginTop: 16 },
  pressed: { opacity: 0.7 },
});
