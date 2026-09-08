import { useState } from 'react';
import * as Linking from 'expo-linking';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  Share,
  Text,
  View,
} from 'react-native';

import type { Capability, CapabilitySelection, Connection, ConnectionDraft, Skill, SkillDetail, SkillDraft } from '@/lib/types';
import { PageSheet } from '@/components/page-sheet';

import { ConnectionEditor, draftForConnection, emptyConnectionDraft } from './connection-editor';
import { SkillForm, SkillView } from './skill-details';
import { styles } from './skill-library.styles';
import { HowCapabilitiesWork, ToolList } from './tool-list';

const emptyDraft: SkillDraft = {
  name: '',
  description: '',
  instructions: '',
  requiredToolIds: [],
  visibility: 'private',
};

type LibraryTab = 'skills' | 'tools';
type LibraryMode = 'list' | 'view' | 'edit' | 'copy' | 'new' | 'newConnection' | 'editConnection';

type Props = {
  skills: Skill[];
  tools: Capability[];
  onClose: () => void;
  onLoad: (skillId: string) => Promise<SkillDetail>;
  onSave: (draft: SkillDraft, skillId?: string) => Promise<SkillDetail>;
  onShare: (skillId: string) => Promise<string>;
  onSaveConnection: (draft: ConnectionDraft, connectionId?: string) => Promise<Connection>;
  onDeleteConnection: (connectionId: string) => Promise<void>;
  onBeginGmailConnection: (returnUrl: string) => Promise<string>;
  onChanged: () => Promise<void>;
  onUse: (capability: CapabilitySelection) => void;
};

export function SkillLibrary({
  skills,
  tools,
  onClose,
  onLoad,
  onSave,
  onShare,
  onSaveConnection,
  onDeleteConnection,
  onBeginGmailConnection,
  onChanged,
  onUse,
}: Props) {
  const [selected, setSelected] = useState<SkillDetail>();
  const [draft, setDraft] = useState<SkillDraft>(emptyDraft);
  const [connection, setConnection] = useState<Connection>();
  const [connectionDraft, setConnectionDraft] = useState<ConnectionDraft>(emptyConnectionDraft);
  const [mode, setMode] = useState<LibraryMode>('list');
  const [tab, setTab] = useState<LibraryTab>('skills');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const open = async (skill: Skill) => {
    setSelected({ ...skill, instructions: '' });
    setError('');
    setMode('view');
    setBusy(true);
    try {
      setSelected(await onLoad(skill.id));
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not load this skill.');
    } finally {
      setBusy(false);
    }
  };

  const startEdit = () => {
    if (!selected) return;
    setDraft({
      name: selected.name,
      description: selected.description,
      instructions: selected.instructions,
      requiredToolIds: selected.requiredToolIds,
      visibility: selected.visibility === 'link' ? 'link' : 'private',
    });
    setMode('edit');
  };

  const startCustomize = () => {
    if (!selected) return;
    setDraft({
      name: `${selected.name} copy`,
      description: selected.description,
      instructions: selected.instructions,
      requiredToolIds: selected.requiredToolIds,
      visibility: 'private',
    });
    setMode('copy');
  };

  const startNew = () => {
    setSelected(undefined);
    setDraft(emptyDraft);
    setError('');
    setMode('new');
  };

  const openConnection = (value?: Connection) => {
    setConnection(value);
    setConnectionDraft(value ? draftForConnection(value) : emptyConnectionDraft);
    setError('');
    setMode(value ? 'editConnection' : 'newConnection');
  };

  const save = async () => {
    if (!draft.name.trim() || !draft.description.trim() || !draft.instructions.trim()) {
      setError('Add a name, summary, and full instructions.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const saved = await onSave(
        {
          ...draft,
          name: draft.name.trim(),
          description: draft.description.trim(),
          instructions: draft.instructions.trim(),
        },
        mode === 'edit' ? selected?.id : undefined,
      );
      await onChanged();
      setSelected(saved);
      setMode('view');
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not save this skill.');
    } finally {
      setBusy(false);
    }
  };

  const share = async () => {
    if (!selected) return;
    setBusy(true);
    setError('');
    try {
      const url = await onShare(selected.id);
      await Share.share({
        title: `Share ${selected.name}`,
        message: `Add the ${selected.name} skill to FroggyBot: ${url}`,
        url,
      });
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not share this skill.');
    } finally {
      setBusy(false);
    }
  };

  const saveConnection = async () => {
    if (!connectionDraft.name.trim() || !connectionDraft.description.trim() || !connectionDraft.endpoint.trim()) {
      setError('Add a name, description, and MCP server URL.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await onSaveConnection(
        {
          ...connectionDraft,
          name: connectionDraft.name.trim(),
          description: connectionDraft.description.trim(),
          endpoint: connectionDraft.endpoint.trim(),
          headerName: connectionDraft.headerName.trim(),
        },
        mode === 'editConnection' ? connection?.id : undefined,
      );
      await onChanged();
      setConnection(undefined);
      setMode('list');
      setTab('tools');
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not save this connection.');
    } finally {
      setBusy(false);
    }
  };

  const connectGmail = async () => {
    setBusy(true);
    setError('');
    try {
      const returnUrl = Linking.createURL('app', { queryParams: { oauth: 'gmail' } });
      const authorizationUrl = await onBeginGmailConnection(returnUrl);
      await Linking.openURL(authorizationUrl);
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not start the Gmail connection.');
    } finally {
      setBusy(false);
    }
  };

  const removeConnection = () => {
    if (!connection) return;
    Alert.alert(
      'Remove connection?',
      'Its credential will enter a seven-day recovery window. Skills and shared links never contain the credential.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Remove',
          style: 'destructive',
          onPress: () => {
            setBusy(true);
            onDeleteConnection(connection.id)
              .then(onChanged)
              .then(() => {
                setConnection(undefined);
                setMode('list');
                setTab('tools');
              })
              .catch((value: unknown) => {
                setError(value instanceof Error ? value.message : 'Could not remove this connection.');
              })
              .finally(() => setBusy(false));
          },
        },
      ],
    );
  };

  const back = () => {
    setError('');
    setMode(
      mode === 'edit' || mode === 'copy' || mode === 'new'
        ? selected ? 'view' : 'list'
        : 'list',
    );
  };

  const title =
    mode === 'list'
      ? 'Skills & tools'
      : mode === 'new'
        ? 'New skill'
      : mode === 'copy'
        ? 'Make editable copy'
        : mode === 'newConnection'
          ? 'Add connection'
          : mode === 'editConnection'
            ? connection?.name
          : selected?.name;

  return (
    <PageSheet accessibilityLabel="Skills and tools" onClose={onClose}>
      <KeyboardAvoidingView style={styles.page} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.header}>
          <Pressable accessibilityRole="button" hitSlop={12} onPress={mode === 'list' ? onClose : back}>
            <Text style={styles.headerAction}>{mode === 'list' ? 'Close' : 'Back'}</Text>
          </Pressable>
          <Text numberOfLines={1} style={styles.title}>{title}</Text>
          {mode === 'list' ? (
            <Pressable accessibilityRole="button" hitSlop={12} onPress={() => tab === 'skills' ? startNew() : openConnection()}>
              <Text style={[styles.headerAction, styles.primary]}>{tab === 'skills' ? 'New skill' : 'Add tool'}</Text>
            </Pressable>
          ) : mode === 'editConnection' && connection?.authType === 'oauth' ? (
            <Pressable accessibilityRole="button" hitSlop={12} onPress={back}>
              <Text style={[styles.headerAction, styles.primary]}>Done</Text>
            </Pressable>
          ) : mode === 'edit' || mode === 'copy' || mode === 'new' || mode === 'newConnection' || mode === 'editConnection' ? (
            <Pressable
              accessibilityRole="button"
              accessibilityState={{ busy, disabled: busy }}
              hitSlop={12}
              disabled={busy}
              onPress={mode === 'newConnection' || mode === 'editConnection' ? saveConnection : save}>
              {busy ? <ActivityIndicator color="#007A3D" /> : <Text style={[styles.headerAction, styles.primary]}>Save</Text>}
            </Pressable>
          ) : (
            <View style={styles.headerSpacer} />
          )}
        </View>

        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          {mode === 'list' ? (
            <>
              <HowCapabilitiesWork />
              <View accessibilityRole="tablist" style={styles.tabs}>
                {(['skills', 'tools'] as const).map((value) => (
                  <Pressable
                    key={value}
                    accessibilityRole="tab"
                    accessibilityState={{ selected: tab === value }}
                    aria-selected={tab === value}
                    style={[styles.tab, tab === value && styles.tabActive]}
                    onPress={() => setTab(value)}>
                    <Text style={[styles.tabText, tab === value && styles.tabTextActive]}>
                      {value === 'skills' ? `Skills · ${skills.length}` : `Tools · ${tools.length}`}
                    </Text>
                  </Pressable>
                ))}
              </View>
              {tab === 'skills' ? (
                <>
                  <Text style={styles.sectionLabel}>Available skills</Text>
                  {skills.map((skill) => (
                    <Pressable
                      accessibilityRole="button"
                      key={skill.id}
                      style={({ pressed }) => [styles.card, pressed && styles.pressed]}
                      onPress={() => open(skill)}>
                      <View style={styles.skillMark}><Text style={styles.skillMarkText}>S</Text></View>
                      <View style={styles.cardText}>
                        <View style={styles.nameRow}>
                          <Text style={styles.skillName}>{skill.name}</Text>
                          <Text style={styles.badge}>
                            {skill.source === 'official' ? 'FroggyBot' : skill.relationship === 'owner' ? 'Yours' : 'Shared'}
                          </Text>
                        </View>
                        <Text style={styles.skillDescription}>{skill.description}</Text>
                        <Text style={styles.cardMeta}>
                          {skill.requiredToolIds.length
                            ? `${skill.requiredToolIds.length} required ${skill.requiredToolIds.length === 1 ? 'tool' : 'tools'}`
                            : 'No tools required'}
                        </Text>
                      </View>
                      <Text style={styles.chevron}>›</Text>
                    </Pressable>
                  ))}
                </>
              ) : (
                <ToolList tools={tools} onUse={onUse} onManage={openConnection} onConnectGmail={connectGmail} />
              )}
            </>
          ) : mode === 'view' ? (
            <SkillView
              skill={selected}
              tools={tools}
              busy={busy}
              onEdit={startEdit}
              onCustomize={startCustomize}
              onShare={share}
              onUse={() => onUse({ kind: 'skill', id: selected?.id ?? '' })}
            />
          ) : mode === 'newConnection' || mode === 'editConnection' ? (
            <ConnectionEditor
              connection={connection}
              draft={connectionDraft}
              onChange={setConnectionDraft}
              onDelete={removeConnection}
              onReconnect={connectGmail}
            />
          ) : (
            <SkillForm draft={draft} tools={tools} onChange={setDraft} />
          )}
          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </PageSheet>
  );
}
