import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { Bot, ScheduleRun } from '@/lib/types';

type Props = {
  bot: Pick<Bot, 'id' | 'name' | 'color'>;
  onList: (botId: string) => Promise<ScheduleRun[]>;
  onApprove?: (runId: string) => Promise<void>;
  onCancel?: (runId: string) => Promise<void>;
  onRetry: (scheduleId: string) => Promise<void>;
  onOpenChat: () => void;
};

const activeStatuses = new Set<ScheduleRun['status']>([
  'waiting',
  'pending',
  'running',
  'needs_input',
  'awaiting_approval',
]);

const statusLabel = (status: ScheduleRun['status']) => ({
  waiting: 'Queued',
  pending: 'Starting',
  running: 'Running',
  needs_input: 'Needs input',
  awaiting_approval: 'Needs approval',
  complete: 'Complete',
  cancelled: 'Stopped',
  error: 'Failed',
}[status]);

const runDate = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
};

export function ScheduleRunList({ bot, onList, onApprove, onCancel, onRetry, onOpenChat }: Props) {
  const [runs, setRuns] = useState<ScheduleRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyRunId, setBusyRunId] = useState<string>();
  const [error, setError] = useState('');

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      setRuns(await onList(bot.id));
      setError('');
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not load recent runs.');
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [bot.id, onList]);

  useEffect(() => {
    let active = true;
    onList(bot.id)
      .then((value) => {
        if (active) {
          setRuns(value);
          setError('');
        }
      })
      .catch((value) => {
        if (active) setError(value instanceof Error ? value.message : 'Could not load recent runs.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [bot.id, onList]);

  useEffect(() => {
    if (!runs.some((run) => activeStatuses.has(run.status))) return;
    const timer = setInterval(() => void load(true), 2_500);
    return () => clearInterval(timer);
  }, [load, runs]);

  const act = async (run: ScheduleRun, action: 'approve' | 'cancel' | 'retry') => {
    setBusyRunId(run.id);
    setError('');
    try {
      if (action === 'approve') await onApprove?.(run.id);
      else if (action === 'retry') await onRetry(run.scheduleId);
      else await onCancel?.(run.id);
      await load(true);
    } catch (value) {
      setError(value instanceof Error ? value.message : `Could not ${action} this run.`);
    } finally {
      setBusyRunId(undefined);
    }
  };

  if (loading) {
    return (
      <View accessibilityLabel="Loading recent runs" accessibilityRole="progressbar" style={styles.center}>
        <ActivityIndicator color="#007A3D" />
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.content}>
      <View style={styles.intro}>
        <Text style={styles.introTitle}>Every run, in one place</Text>
        <Text style={styles.introText}>
          See what finished, what failed, and anything waiting for your approval.
        </Text>
      </View>
      {error ? (
        <View style={styles.errorCard}>
          <Text accessibilityRole="alert" style={styles.error}>{error}</Text>
          <Pressable accessibilityRole="button" onPress={() => void load()}>
            <Text style={styles.retry}>Try again</Text>
          </Pressable>
        </View>
      ) : null}
      {!runs.length ? (
        <View style={styles.center}>
          <Text style={styles.emptyTitle}>No runs yet</Text>
          <Text style={styles.emptyText}>Run a scheduled task and its progress will appear here.</Text>
        </View>
      ) : (
        runs.map((run) => {
          const busy = busyRunId === run.id;
          const attention = run.status === 'awaiting_approval' || run.status === 'needs_input' || run.status === 'error';
          return (
            <View key={run.id} style={[styles.run, attention && styles.runAttention]}>
              <View style={styles.runHeading}>
                <View style={styles.runTitleWrap}>
                  <Text numberOfLines={1} style={styles.runTitle}>{run.scheduleName}</Text>
                  <Text style={styles.runDate}>{runDate(run.createdAt)}</Text>
                </View>
                <View style={[styles.status, attention && styles.statusAttention]}>
                  <Text style={[styles.statusText, attention && styles.statusTextAttention]}>
                    {statusLabel(run.status)}
                  </Text>
                </View>
              </View>
              <Text numberOfLines={2} style={styles.prompt}>{run.prompt}</Text>
              {run.activity?.length && activeStatuses.has(run.status) ? (
                <Text accessibilityLiveRegion="polite" style={styles.activity}>
                  {run.activity[run.activity.length - 1]}
                </Text>
              ) : null}
              {run.output ? <Text numberOfLines={5} style={styles.output}>{run.output}</Text> : null}
              {run.attachments?.length ? (
                <Text style={styles.files}>{run.attachments.length} {run.attachments.length === 1 ? 'file' : 'files'} created</Text>
              ) : null}
              {run.status === 'awaiting_approval' && onApprove && onCancel ? (
                <View style={styles.approval}>
                  <Text style={styles.approvalText}>
                    Allow once: {(run.approvalTools ?? []).join(', ') || 'interactive tools'}
                  </Text>
                  <View style={styles.actions}>
                    <Pressable
                      accessibilityRole="button"
                      accessibilityState={{ busy, disabled: busy }}
                      disabled={busy}
                      style={styles.primaryButton}
                      onPress={() => void act(run, 'approve')}>
                      {busy ? <ActivityIndicator color="white" size="small" /> : <Text style={styles.primaryLabel}>Allow once</Text>}
                    </Pressable>
                    <Pressable
                      accessibilityRole="button"
                      disabled={busy}
                      style={styles.secondaryButton}
                      onPress={() => void act(run, 'cancel')}>
                      <Text style={styles.secondaryLabel}>Stop run</Text>
                    </Pressable>
                  </View>
                </View>
              ) : activeStatuses.has(run.status) && onCancel ? (
                <Pressable
                  accessibilityRole="button"
                  disabled={busy}
                  style={styles.stopButton}
                  onPress={() => void act(run, 'cancel')}>
                  <Text style={styles.stopLabel}>{busy ? 'Stopping…' : 'Stop run'}</Text>
                </Pressable>
              ) : run.status === 'error' ? (
                <View style={styles.actions}>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityState={{ busy, disabled: busy }}
                    disabled={busy}
                    style={styles.primaryButton}
                    onPress={() => void act(run, 'retry')}>
                    {busy ? <ActivityIndicator color="white" size="small" /> : <Text style={styles.primaryLabel}>Retry run</Text>}
                  </Pressable>
                  <Pressable accessibilityRole="button" style={styles.chatButton} onPress={onOpenChat}>
                    <Text style={styles.chatLabel}>View in chat</Text>
                  </Pressable>
                </View>
              ) : run.output || run.attachments?.length ? (
                <Pressable accessibilityRole="button" style={styles.chatButton} onPress={onOpenChat}>
                  <Text style={styles.chatLabel}>View in chat</Text>
                </Pressable>
              ) : null}
            </View>
          );
        })
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { width: '100%', maxWidth: 680, alignSelf: 'center', padding: 20, paddingBottom: 60, gap: 12 },
  center: { minHeight: 240, alignItems: 'center', justifyContent: 'center', padding: 28 },
  intro: { padding: 16, borderRadius: 17, backgroundColor: '#EAF5EF', borderWidth: 1, borderColor: '#CBE2D5', marginBottom: 4 },
  introTitle: { color: '#173E2A', fontSize: 16, fontWeight: '800' },
  introText: { color: '#536D5F', fontSize: 13, lineHeight: 19, marginTop: 4 },
  errorCard: { padding: 13, borderRadius: 13, backgroundColor: '#FCEBE7', flexDirection: 'row', gap: 12, alignItems: 'center' },
  error: { flex: 1, color: '#92382F', fontSize: 13 },
  retry: { color: '#007A3D', fontSize: 13, fontWeight: '800' },
  emptyTitle: { color: '#24231F', fontSize: 17, fontWeight: '800' },
  emptyText: { color: '#6E6A62', fontSize: 13, lineHeight: 19, textAlign: 'center', marginTop: 6 },
  run: { padding: 16, borderRadius: 17, borderWidth: 1, borderColor: '#E0DDD5', backgroundColor: 'white' },
  runAttention: { borderColor: '#E0AF76', backgroundColor: '#FFF9F0' },
  runHeading: { flexDirection: 'row', alignItems: 'flex-start', gap: 12 },
  runTitleWrap: { flex: 1, minWidth: 0 },
  runTitle: { color: '#24231F', fontSize: 15, fontWeight: '800' },
  runDate: { color: '#6E6A62', fontSize: 11, marginTop: 3 },
  status: { borderRadius: 10, backgroundColor: '#E6F2EB', paddingHorizontal: 8, paddingVertical: 4 },
  statusAttention: { backgroundColor: '#F6E2C8' },
  statusText: { color: '#17643C', fontSize: 10, fontWeight: '800' },
  statusTextAttention: { color: '#824B14' },
  prompt: { color: '#6E6A62', fontSize: 12, lineHeight: 17, marginTop: 10 },
  activity: { color: '#17643C', fontSize: 12, fontWeight: '700', marginTop: 10 },
  output: { color: '#34322D', fontSize: 13, lineHeight: 19, marginTop: 11 },
  files: { color: '#17643C', fontSize: 11, fontWeight: '800', marginTop: 9 },
  approval: { marginTop: 13, paddingTop: 13, borderTopWidth: 1, borderColor: '#E8D5BD' },
  approvalText: { color: '#70451B', fontSize: 12, lineHeight: 17 },
  actions: { flexDirection: 'row', gap: 8, marginTop: 11 },
  primaryButton: { minHeight: 44, borderRadius: 12, paddingHorizontal: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: '#007A3D' },
  primaryLabel: { color: 'white', fontSize: 13, fontWeight: '800' },
  secondaryButton: { minHeight: 44, borderRadius: 12, paddingHorizontal: 14, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: '#D8C5AD' },
  secondaryLabel: { color: '#70451B', fontSize: 13, fontWeight: '800' },
  stopButton: { minHeight: 44, justifyContent: 'center', alignSelf: 'flex-start', marginTop: 8 },
  stopLabel: { color: '#A0493D', fontSize: 12, fontWeight: '800' },
  chatButton: { minHeight: 44, justifyContent: 'center', alignSelf: 'flex-start', marginTop: 6 },
  chatLabel: { color: '#007A3D', fontSize: 12, fontWeight: '800' },
});
