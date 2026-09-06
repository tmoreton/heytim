import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import type { Connection, ConnectionDraft } from '@/lib/types';

export const emptyConnectionDraft: ConnectionDraft = {
  name: '',
  description: '',
  endpoint: '',
  authType: 'none',
  headerName: 'X-API-Key',
  credential: '',
  risk: 'interactive',
};

export const draftForConnection = (connection: Connection): ConnectionDraft => ({
  name: connection.name,
  description: connection.description,
  endpoint: connection.endpoint,
  authType: connection.authType,
  headerName: connection.headerName ?? 'X-API-Key',
  credential: '',
  risk: connection.risk === 'read' ? 'read' : 'interactive',
});

export function ConnectionEditor({
  connection,
  draft,
  onChange,
  onDelete,
  onReconnect,
}: {
  connection?: Connection;
  draft: ConnectionDraft;
  onChange: (draft: ConnectionDraft) => void;
  onDelete: () => void;
  onReconnect: () => void;
}) {
  if (connection?.authType === 'oauth') {
    return (
      <>
        <View style={styles.oauthCard}>
          <Text style={styles.oauthTitle}>Gmail is connected</Text>
          <Text style={styles.oauthAccount}>{connection.connectedAccount}</Text>
          <Text style={styles.oauthText}>
            FroggyBot can search and read email and create drafts for review. It cannot send, delete, relabel, archive, or mark messages.
          </Text>
        </View>
        <View style={styles.warning}>
          <Text style={styles.warningTitle}>Approval is required by default</Text>
          <Text style={styles.warningText}>
            Email can contain unsafe instructions. You can always allow Gmail for a bot, but it still cannot run in
            groups or scheduled tasks.
          </Text>
        </View>
        <Pressable accessibilityRole="button" style={styles.reconnectButton} onPress={onReconnect}>
          <Text style={styles.reconnectText}>Reconnect Gmail</Text>
        </Pressable>
        <Pressable accessibilityRole="button" style={styles.deleteButton} onPress={onDelete}>
          <Text style={styles.deleteText}>Remove connection</Text>
        </Pressable>
      </>
    );
  }

  return (
    <>
      <View style={styles.warning}>
        <Text style={styles.warningTitle}>Connect only servers you trust</Text>
        <Text style={styles.warningText}>
          This private MCP server can receive information sent to its tools. Credentials are encrypted and never added to skills or shared links.
        </Text>
      </View>

      <Text style={styles.label}>Name</Text>
      <TextInput
        accessibilityLabel="Connection name"
        style={styles.input}
        value={draft.name}
        onChangeText={(name) => onChange({ ...draft, name })}
        placeholder="My notes"
        placeholderTextColor="#9B978F"
        maxLength={80}
      />

      <Text style={styles.label}>What can it do?</Text>
      <TextInput
        accessibilityLabel="Connection description"
        style={styles.input}
        value={draft.description}
        onChangeText={(description) => onChange({ ...draft, description })}
        placeholder="Search and update my notes"
        placeholderTextColor="#9B978F"
        maxLength={240}
      />

      <Text style={styles.label}>MCP server URL</Text>
      <Text style={styles.help}>Use a public HTTPS URL without credentials in the address.</Text>
      <TextInput
        accessibilityLabel="MCP server URL"
        style={styles.input}
        value={draft.endpoint}
        onChangeText={(endpoint) => onChange({ ...draft, endpoint })}
        placeholder="https://mcp.example.com/mcp"
        placeholderTextColor="#9B978F"
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
        maxLength={500}
      />

      <Text style={styles.label}>Authentication</Text>
      <View style={styles.choices}>
        {([
          ['none', 'None'],
          ['bearer', 'Bearer token'],
          ['api_key', 'API key'],
        ] as const).map(([value, label]) => (
          <Pressable
            key={value}
            accessibilityRole="radio"
            accessibilityState={{ checked: draft.authType === value }}
            style={[styles.choice, draft.authType === value && styles.choiceActive]}
            onPress={() => onChange({ ...draft, authType: value })}>
            <Text style={[styles.choiceText, draft.authType === value && styles.choiceTextActive]}>{label}</Text>
          </Pressable>
        ))}
      </View>

      {draft.authType === 'api_key' ? (
        <>
          <Text style={styles.label}>API key header</Text>
          <TextInput
            accessibilityLabel="API key header"
            style={styles.input}
            value={draft.headerName}
            onChangeText={(headerName) => onChange({ ...draft, headerName })}
            placeholder="X-API-Key"
            placeholderTextColor="#9B978F"
            autoCapitalize="none"
            autoCorrect={false}
            maxLength={64}
          />
        </>
      ) : null}

      {draft.authType !== 'none' ? (
        <>
          <Text style={styles.label}>{draft.authType === 'bearer' ? 'Bearer token' : 'API key'}</Text>
          <Text style={styles.help}>
            {connection?.hasCredential ? 'Leave blank to keep the current credential.' : 'Saved securely after you connect.'}
          </Text>
          <TextInput
            accessibilityLabel="Connection credential"
            style={styles.input}
            value={draft.credential}
            onChangeText={(credential) => onChange({ ...draft, credential })}
            placeholder={connection?.hasCredential ? 'Current credential is hidden' : 'Paste credential'}
            placeholderTextColor="#9B978F"
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry
            maxLength={4096}
          />
        </>
      ) : null}

      <Text style={styles.label}>Access</Text>
      <Text style={styles.help}>
        Connections that can change data require approval by default. You can always allow one for a bot in direct
        chats, but it cannot run in groups or scheduled tasks.
      </Text>
      <View style={styles.accessChoices}>
        {([
          ['read', 'Read only', 'The server only looks things up.'],
          ['interactive', 'Can make changes', 'The server may create, edit, send, or delete.'],
        ] as const).map(([value, label, detail]) => (
          <Pressable
            key={value}
            accessibilityRole="radio"
            accessibilityState={{ checked: draft.risk === value }}
            style={[styles.accessChoice, draft.risk === value && styles.accessChoiceActive]}
            onPress={() => onChange({ ...draft, risk: value })}>
            <Text style={styles.accessTitle}>{label}</Text>
            <Text style={styles.accessText}>{detail}</Text>
          </Pressable>
        ))}
      </View>

      {connection ? (
        <Pressable accessibilityRole="button" style={styles.deleteButton} onPress={onDelete}>
          <Text style={styles.deleteText}>Remove connection</Text>
        </Pressable>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  warning: { padding: 16, borderRadius: 17, borderWidth: 1, borderColor: '#E6D6A8', backgroundColor: '#FFF9E8' },
  warningTitle: { color: '#5D4811', fontSize: 15, fontWeight: '800' },
  warningText: { color: '#756126', fontSize: 13, lineHeight: 19, marginTop: 4 },
  oauthCard: { padding: 18, borderRadius: 18, borderWidth: 1, borderColor: '#CBE2D5', backgroundColor: '#E9F4EE', marginBottom: 12 },
  oauthTitle: { color: '#173E2A', fontSize: 17, fontWeight: '800' },
  oauthAccount: { color: '#007A3D', fontSize: 14, fontWeight: '700', marginTop: 5 },
  oauthText: { color: '#527060', fontSize: 13, lineHeight: 20, marginTop: 10 },
  label: { color: '#24231F', fontSize: 14, fontWeight: '700', marginTop: 20, marginBottom: 8 },
  help: { color: '#858179', fontSize: 12, lineHeight: 17, marginTop: -4, marginBottom: 9 },
  input: { minHeight: 48, paddingHorizontal: 14, paddingVertical: 12, borderRadius: 14, borderWidth: 1, borderColor: '#DDDAD2', backgroundColor: 'white', color: '#24231F', fontSize: 15 },
  choices: { flexDirection: 'row', gap: 7 },
  choice: { flex: 1, minHeight: 42, paddingHorizontal: 6, borderRadius: 12, borderWidth: 1, borderColor: '#DDDAD2', alignItems: 'center', justifyContent: 'center', backgroundColor: 'white' },
  choiceActive: { borderColor: '#75A98C', backgroundColor: '#EAF5EF' },
  choiceText: { color: '#77736B', fontSize: 12, fontWeight: '700', textAlign: 'center' },
  choiceTextActive: { color: '#007A3D' },
  accessChoices: { gap: 8 },
  accessChoice: { padding: 14, borderRadius: 14, borderWidth: 1, borderColor: '#DDDAD2', backgroundColor: 'white' },
  accessChoiceActive: { borderColor: '#75A98C', backgroundColor: '#EAF5EF' },
  accessTitle: { color: '#2B2A25', fontSize: 14, fontWeight: '700' },
  accessText: { color: '#77736B', fontSize: 12, lineHeight: 17, marginTop: 3 },
  deleteButton: { minHeight: 47, marginTop: 32, borderRadius: 14, borderWidth: 1, borderColor: '#E2B9B4', alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFF8F7' },
  deleteText: { color: '#A53A32', fontSize: 14, fontWeight: '700' },
  reconnectButton: { minHeight: 47, marginTop: 24, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: '#007A3D' },
  reconnectText: { color: 'white', fontSize: 14, fontWeight: '800' },
});
