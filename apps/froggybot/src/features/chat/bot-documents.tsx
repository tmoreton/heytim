import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { BotAvatar } from '@/components/bot-avatar';
import type { Bot, BotDocument } from '@/lib/types';

type Props = {
  bot: Bot;
  onClose: () => void;
  onList: (botId: string) => Promise<BotDocument[]>;
  onOpen: (document: BotDocument) => Promise<void>;
};

const fileSize = (bytes: number) =>
  bytes >= 1_000_000
    ? `${(bytes / 1_000_000).toFixed(bytes >= 10_000_000 ? 0 : 1)} MB`
    : `${Math.max(1, Math.round(bytes / 1_000))} KB`;

const createdDate = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? ''
    : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
};

export function BotDocuments({ bot, onClose, onList, onOpen }: Props) {
  const [documents, setDocuments] = useState<BotDocument[]>([]);
  const [openingId, setOpeningId] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    onList(bot.id)
      .then((value) => {
        if (active) setDocuments(value);
      })
      .catch((value: unknown) => {
        if (active) setError(value instanceof Error ? value.message : 'Could not load documents.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [bot.id, onList]);

  const open = async (document: BotDocument) => {
    setOpeningId(document.id);
    setError('');
    try {
      await onOpen(document);
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not open that document.');
    } finally {
      setOpeningId(undefined);
    }
  };

  return (
    <Modal visible animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={styles.page}>
        <View style={styles.header}>
          <Text accessibilityRole="header" style={styles.title}>Documents</Text>
          <Pressable accessibilityRole="button" hitSlop={12} onPress={onClose}>
            <Text style={styles.done}>Done</Text>
          </Pressable>
        </View>
        <ScrollView contentContainerStyle={styles.content}>
          <View style={styles.intro}>
            <BotAvatar name={bot.name} color={bot.color} size={54} />
            <View style={styles.introCopy}>
              <Text style={styles.introTitle}>{`${bot.name}'s files`}</Text>
              <Text style={styles.introText}>
                {`Generated files stay here if you clear the conversation. Deleting ${bot.name} permanently removes them.`}
              </Text>
            </View>
          </View>

          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
          {loading ? (
            <ActivityIndicator color="#007A3D" style={styles.loader} />
          ) : documents.length ? (
            <View style={styles.documentList}>
              {documents.map((document) => {
                const opening = openingId === document.id;
                return (
                  <Pressable
                    key={document.id}
                    accessibilityLabel={`Open ${document.name}`}
                    accessibilityRole="button"
                    accessibilityState={{ busy: opening, disabled: Boolean(openingId) }}
                    disabled={Boolean(openingId)}
                    style={({ pressed }) => [styles.document, pressed && styles.pressed]}
                    onPress={() => void open(document)}>
                    <View style={styles.formatBadge}>
                      <Text style={styles.formatText}>{document.format.toUpperCase().slice(0, 5)}</Text>
                    </View>
                    <View style={styles.documentCopy}>
                      <Text numberOfLines={2} style={styles.documentName}>{document.name}</Text>
                      <Text style={styles.documentMeta}>
                        {[fileSize(document.size), createdDate(document.createdAt)].filter(Boolean).join(' · ')}
                      </Text>
                    </View>
                    {opening ? (
                      <ActivityIndicator size="small" color="#007A3D" />
                    ) : (
                      <Text style={styles.openText}>Open</Text>
                    )}
                  </Pressable>
                );
              })}
            </View>
          ) : (
            <View style={styles.empty}>
              <Text style={styles.emptyTitle}>No documents yet</Text>
              <Text style={styles.emptyText}>
                {`Files that ${bot.name} creates will appear here automatically.`}
              </Text>
            </View>
          )}
        </ScrollView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: '#F8F7F3' },
  header: { minHeight: 64, paddingHorizontal: 20, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderBottomWidth: StyleSheet.hairlineWidth, borderColor: '#DEDAD2' },
  title: { color: '#201F1B', fontSize: 22, fontWeight: '800' },
  done: { color: '#007A3D', fontSize: 16, fontWeight: '700' },
  content: { width: '100%', maxWidth: 680, alignSelf: 'center', padding: 20, paddingBottom: 60 },
  intro: { flexDirection: 'row', alignItems: 'center', gap: 14, borderRadius: 20, backgroundColor: '#E8F3ED', padding: 17 },
  introCopy: { flex: 1 },
  introTitle: { color: '#1E3C2C', fontSize: 18, fontWeight: '800' },
  introText: { color: '#4D6758', fontSize: 13, lineHeight: 19, marginTop: 5 },
  error: { color: '#9E342A', backgroundColor: '#FCECE8', padding: 12, borderRadius: 12, fontSize: 13, marginTop: 16 },
  loader: { marginVertical: 54 },
  documentList: { marginTop: 20, borderRadius: 18, overflow: 'hidden', borderWidth: 1, borderColor: '#E2DFD8' },
  document: { minHeight: 78, flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 14, paddingVertical: 12, backgroundColor: '#FFFFFF', borderBottomWidth: StyleSheet.hairlineWidth, borderColor: '#E2DFD8' },
  formatBadge: { width: 46, height: 46, borderRadius: 12, alignItems: 'center', justifyContent: 'center', backgroundColor: '#E1F1E8' },
  formatText: { color: '#007A3D', fontSize: 10, fontWeight: '900', letterSpacing: 0.4 },
  documentCopy: { flex: 1 },
  documentName: { color: '#282722', fontSize: 15, lineHeight: 20, fontWeight: '700' },
  documentMeta: { color: '#8B877F', fontSize: 12, marginTop: 4 },
  openText: { color: '#007A3D', fontSize: 13, fontWeight: '800' },
  empty: { alignItems: 'center', padding: 34, marginTop: 22, borderRadius: 20, borderWidth: 1, borderStyle: 'dashed', borderColor: '#D8D4CB' },
  emptyTitle: { color: '#24231F', fontSize: 17, fontWeight: '800' },
  emptyText: { color: '#858179', fontSize: 13, lineHeight: 19, textAlign: 'center', marginTop: 6 },
  pressed: { opacity: 0.68 },
});
