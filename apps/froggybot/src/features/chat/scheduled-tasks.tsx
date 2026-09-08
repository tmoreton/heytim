import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from 'react-native';

import { ActionSheet } from '@/components/action-sheet';
import { BotAvatar } from '@/components/bot-avatar';
import { PageSheet } from '@/components/page-sheet';
import { describeSchedule, deviceTimezone, formatTime, latestRunLabel, parseTimeInput, WEEKDAYS } from '@/lib/schedules';
import type { Bot, ScheduleRun, ScheduledTask, ScheduledTaskDraft } from '@/lib/types';

import { ScheduleRunList } from './schedule-run-list';

type Props = {
  bot: Pick<Bot, 'id' | 'name' | 'color'>;
  onClose: () => void;
  onList: (botId: string) => Promise<ScheduledTask[]>;
  onListRuns: (botId: string) => Promise<ScheduleRun[]>;
  onSave: (botId: string, draft: ScheduledTaskDraft, scheduleId?: string) => Promise<ScheduledTask>;
  onDelete: (botId: string, scheduleId: string) => Promise<void>;
  onRun: (botId: string, scheduleId: string) => Promise<void>;
  onApproveRun?: (runId: string) => Promise<void>;
  onCancelRun?: (runId: string) => Promise<void>;
  onTriggered: () => Promise<void>;
};

const newDraft = (): ScheduledTaskDraft => ({
  name: '',
  prompt: '',
  frequency: 'daily',
  time: '09:00',
  timezone: deviceTimezone(),
  enabled: true,
});

export function ScheduledTasks({
  bot,
  onClose,
  onList,
  onListRuns,
  onSave,
  onDelete,
  onRun,
  onApproveRun,
  onCancelRun,
  onTriggered,
}: Props) {
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [editing, setEditing] = useState<ScheduledTask | 'new'>();
  const [pendingDeletion, setPendingDeletion] = useState<ScheduledTask>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState<'tasks' | 'runs'>('tasks');

  useEffect(() => {
    let active = true;
    onList(bot.id)
      .then((value) => {
        if (active) setTasks(value);
      })
      .catch((value) => {
        if (active) setError(value instanceof Error ? value.message : 'Could not load scheduled tasks.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [bot.id, onList]);

  const save = async (draft: ScheduledTaskDraft, scheduleId?: string) => {
    const saved = await onSave(bot.id, draft, scheduleId);
    setTasks((current) => {
      const found = current.some((task) => task.id === saved.id);
      return found ? current.map((task) => (task.id === saved.id ? saved : task)) : [saved, ...current];
    });
    setEditing(undefined);
  };

  const remove = async (task: ScheduledTask) => {
    setError('');
    try {
      await onDelete(bot.id, task.id);
      setTasks((current) => current.filter((item) => item.id !== task.id));
      setEditing(undefined);
    } catch (value) {
      setEditing(undefined);
      setError(value instanceof Error ? value.message : 'Could not delete task. Please try again.');
    }
  };

  const run = async (task: ScheduledTask) => {
    await onRun(bot.id, task.id);
    const current = new Date().toISOString();
    setTasks((items) =>
      items.map((item) => (item.id === task.id ? { ...item, lastRunAt: current, lastStatus: 'pending' } : item)),
    );
    setEditing(undefined);
    await onTriggered();
    setActiveTab('runs');
  };

  return (
    <PageSheet accessibilityLabel="Scheduled work" onClose={onClose}>
      {editing ? (
        <TaskEditor
          key={editing === 'new' ? 'new' : editing.id}
          bot={bot}
          task={editing === 'new' ? undefined : editing}
          onBack={() => setEditing(undefined)}
          onSave={save}
          onDelete={setPendingDeletion}
          onRun={run}
        />
      ) : (
        <View style={styles.page}>
          <View style={styles.header}>
            <Pressable accessibilityRole="button" hitSlop={12} onPress={onClose}>
              <Text style={styles.headerAction}>Done</Text>
            </Pressable>
            <Text accessibilityRole="header" style={styles.headerTitle}>
              {activeTab === 'tasks' ? 'Scheduled tasks' : 'Recent runs'}
            </Text>
            {activeTab === 'tasks' ? (
              <Pressable accessibilityLabel="Create scheduled task" accessibilityRole="button" hitSlop={12} onPress={() => setEditing('new')}>
                <Text style={[styles.headerAction, styles.primaryAction]}>New</Text>
              </Pressable>
            ) : <View style={styles.headerSpacer} />}
          </View>
          <View accessibilityRole="tablist" style={styles.tabs}>
            {(['tasks', 'runs'] as const).map((tab) => (
              <Pressable
                key={tab}
                accessibilityRole="tab"
                accessibilityState={{ selected: activeTab === tab }}
                aria-selected={activeTab === tab}
                style={[styles.tab, activeTab === tab && styles.tabActive]}
                onPress={() => setActiveTab(tab)}>
                <Text style={[styles.tabLabel, activeTab === tab && styles.tabLabelActive]}>
                  {tab === 'tasks' ? 'Tasks' : 'Runs'}
                </Text>
              </Pressable>
            ))}
          </View>
          {activeTab === 'runs' ? (
            <ScheduleRunList
              bot={bot}
              onList={onListRuns}
              onApprove={onApproveRun}
              onCancel={onCancelRun}
              onRetry={async (scheduleId) => {
                await onRun(bot.id, scheduleId);
                await onTriggered();
              }}
              onOpenChat={onClose}
            />
          ) : <ScrollView contentContainerStyle={styles.listContent}>
            <View style={styles.intro}>
              <BotAvatar name={bot.name} color={bot.color} size={58} />
              <View style={styles.introCopy}>
                <Text style={styles.introTitle}>Let {bot.name} handle the routine</Text>
                <Text style={styles.introText}>Choose what to do and when. The result appears here in chat, with a notification when it is ready.</Text>
              </View>
            </View>
            {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
            {loading ? (
              <ActivityIndicator color="#007A3D" style={styles.loader} />
            ) : tasks.length ? (
              <View style={styles.taskList}>
                {tasks.map((task) => {
                  const lastRun = latestRunLabel(task);
                  return (
                    <Pressable
                      key={task.id}
                      accessibilityRole="button"
                      style={({ pressed }) => [styles.task, pressed && styles.pressed]}
                      onPress={() => setEditing(task)}>
                      <View style={[styles.statusDot, !task.enabled && styles.statusDotOff]} />
                      <View style={styles.taskCopy}>
                        <Text style={styles.taskName}>{task.name}</Text>
                        <Text style={styles.taskCadence}>{describeSchedule(task)}</Text>
                        {lastRun ? <Text style={styles.taskRun}>{lastRun}</Text> : null}
                      </View>
                      <Text style={styles.chevron}>›</Text>
                    </Pressable>
                  );
                })}
              </View>
            ) : (
              <View style={styles.empty}>
                <Text style={styles.emptyTitle}>Nothing scheduled yet</Text>
                <Text style={styles.emptyText}>A daily briefing or weekly review is a good first task.</Text>
                <Pressable accessibilityRole="button" style={styles.primaryButton} onPress={() => setEditing('new')}>
                  <Text style={styles.primaryButtonText}>Create a task</Text>
                </Pressable>
              </View>
            )}
          </ScrollView>}
        </View>
      )}
      <ActionSheet
        visible={Boolean(pendingDeletion)}
        title="Delete scheduled task?"
        message={`${pendingDeletion?.name ?? 'This task'} will stop running. Its past chat messages will stay.`}
        options={pendingDeletion
          ? [{ label: 'Delete task', destructive: true, onPress: () => void remove(pendingDeletion) }]
          : []}
        onClose={() => setPendingDeletion(undefined)}
      />
    </PageSheet>
  );
}

function TaskEditor({
  bot,
  task,
  onBack,
  onSave,
  onDelete,
  onRun,
}: {
  bot: Pick<Bot, 'id' | 'name' | 'color'>;
  task?: ScheduledTask;
  onBack: () => void;
  onSave: (draft: ScheduledTaskDraft, scheduleId?: string) => Promise<void>;
  onDelete: (task: ScheduledTask) => void;
  onRun: (task: ScheduledTask) => Promise<void>;
}) {
  const [draft, setDraft] = useState<ScheduledTaskDraft>(() =>
    task
      ? {
          name: task.name,
          prompt: task.prompt,
          frequency: task.frequency,
          dayOfWeek: task.dayOfWeek,
          dayOfMonth: task.dayOfMonth,
          time: task.time,
          timezone: task.timezone,
          enabled: task.enabled,
        }
      : newDraft(),
  );
  const [timeText, setTimeText] = useState(() => formatTime(draft.time));
  const [busy, setBusy] = useState<'save' | 'run'>();
  const [error, setError] = useState('');

  const validatedDraft = (): ScheduledTaskDraft | undefined => {
    const time = parseTimeInput(timeText);
    if (!draft.name.trim() || !draft.prompt.trim()) {
      setError('Give this task a name and tell the bot what to do.');
      return undefined;
    }
    if (!time) {
      setError('Enter a time like 9:00 AM.');
      return undefined;
    }
    if (
      draft.frequency === 'monthly'
      && (!Number.isInteger(draft.dayOfMonth) || (draft.dayOfMonth ?? 0) < 1 || (draft.dayOfMonth ?? 0) > 28)
    ) {
      setError('Choose a day from 1 through 28.');
      return undefined;
    }
    return {
      ...draft,
      name: draft.name.trim(),
      prompt: draft.prompt.trim(),
      time,
      dayOfWeek: draft.frequency === 'weekly' ? draft.dayOfWeek ?? 'MON' : undefined,
      dayOfMonth: draft.frequency === 'monthly' ? draft.dayOfMonth ?? 1 : undefined,
    };
  };

  const save = async () => {
    const value = validatedDraft();
    if (!value) return;
    setBusy('save');
    setError('');
    try {
      await onSave(value, task?.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not save this task.');
    } finally {
      setBusy(undefined);
    }
  };

  const run = async () => {
    if (!task) return;
    setBusy('run');
    setError('');
    try {
      await onRun(task);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not run this task.');
    } finally {
      setBusy(undefined);
    }
  };

  return (
    <KeyboardAvoidingView style={styles.page} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View style={styles.header}>
        <Pressable accessibilityRole="button" hitSlop={12} onPress={onBack}>
          <Text style={styles.headerAction}>Back</Text>
        </Pressable>
        <Text accessibilityRole="header" style={styles.headerTitle}>{task ? 'Edit task' : 'New task'}</Text>
        <Pressable accessibilityRole="button" accessibilityState={{ busy: busy === 'save', disabled: Boolean(busy) }} hitSlop={12} disabled={Boolean(busy)} onPress={save}>
          {busy === 'save' ? <ActivityIndicator color="#007A3D" /> : <Text style={[styles.headerAction, styles.primaryAction]}>Save</Text>}
        </Pressable>
      </View>
      <ScrollView contentContainerStyle={styles.form} keyboardShouldPersistTaps="handled">
        <View style={styles.botLine}>
          <BotAvatar name={bot.name} color={bot.color} size={39} />
          <Text style={styles.botLineText}>{bot.name} will run this task</Text>
        </View>

        <Text style={styles.label}>Task name</Text>
        <TextInput
          accessibilityLabel="Task name"
          style={styles.input}
          value={draft.name}
          maxLength={64}
          placeholder="Morning priorities"
          placeholderTextColor="#6E6A62"
          onChangeText={(name) => setDraft((value) => ({ ...value, name }))}
        />

        <Text style={styles.label}>What should {bot.name} do?</Text>
        <TextInput
          accessibilityLabel="Task instructions"
          style={[styles.input, styles.promptInput]}
          value={draft.prompt}
          maxLength={8000}
          multiline
          textAlignVertical="top"
          placeholder="Review the latest conversation and send me the three priorities for today."
          placeholderTextColor="#6E6A62"
          onChangeText={(prompt) => setDraft((value) => ({ ...value, prompt }))}
        />

        <Text style={styles.label}>Repeat</Text>
        <View accessibilityLabel="Repeat frequency" accessibilityRole="radiogroup" style={styles.frequencyGrid}>
          {([
            ['daily', 'Daily'],
            ['weekdays', 'Weekdays'],
            ['weekly', 'Weekly'],
            ['monthly', 'Monthly'],
          ] as const).map(([frequency, label]) => (
            <Pressable
              key={frequency}
              accessibilityRole="radio"
              accessibilityState={{ checked: draft.frequency === frequency }}
              aria-checked={draft.frequency === frequency}
              style={[styles.frequencyChoice, draft.frequency === frequency && styles.segmentActive]}
              onPress={() => setDraft((value) => ({
                ...value,
                frequency,
                dayOfWeek: frequency === 'weekly' ? value.dayOfWeek ?? 'MON' : undefined,
                dayOfMonth: frequency === 'monthly' ? value.dayOfMonth ?? 1 : undefined,
              }))}>
              <Text style={[styles.segmentText, draft.frequency === frequency && styles.segmentTextActive]}>
                {label}
              </Text>
            </Pressable>
          ))}
        </View>

        {draft.frequency === 'weekly' ? (
          <View accessibilityLabel="Day of week" accessibilityRole="radiogroup" style={styles.dayRow}>
            {WEEKDAYS.map((day) => (
              <Pressable
                key={day.value}
                accessibilityLabel={day.label}
                accessibilityRole="radio"
                accessibilityState={{ checked: draft.dayOfWeek === day.value }}
                aria-checked={draft.dayOfWeek === day.value}
                style={[styles.day, draft.dayOfWeek === day.value && styles.dayActive]}
                onPress={() => setDraft((value) => ({ ...value, dayOfWeek: day.value }))}>
                <Text style={[styles.dayText, draft.dayOfWeek === day.value && styles.dayTextActive]}>{day.short.slice(0, 1)}</Text>
              </Pressable>
            ))}
          </View>
        ) : null}

        {draft.frequency === 'monthly' ? (
          <>
            <Text style={styles.label}>Day of month</Text>
            <TextInput
              accessibilityLabel="Day of month"
              style={styles.input}
              value={String(draft.dayOfMonth ?? 1)}
              keyboardType="number-pad"
              maxLength={2}
              onChangeText={(value) => {
                const dayOfMonth = Number(value.replace(/\D/g, ''));
                setDraft((current) => ({ ...current, dayOfMonth }));
              }}
            />
            <Text style={styles.help}>Choose day 1 through 28 so the task runs every month.</Text>
          </>
        ) : null}

        <Text style={styles.label}>Time</Text>
        <TextInput
          accessibilityLabel="Task time"
          style={styles.input}
          value={timeText}
          maxLength={8}
          placeholder="9:00 AM"
          placeholderTextColor="#6E6A62"
          onChangeText={setTimeText}
          onBlur={() => {
            const parsed = parseTimeInput(timeText);
            if (parsed) setTimeText(formatTime(parsed));
          }}
        />
        <Text style={styles.help}>Uses {draft.timezone.replaceAll('_', ' ')} and follows daylight saving time.</Text>

        <View style={styles.enabledRow}>
          <View style={styles.enabledCopy}>
            <Text style={styles.enabledTitle}>Task is active</Text>
            <Text style={styles.help}>Turn this off to pause without deleting it.</Text>
          </View>
          <Switch
            accessibilityLabel="Task is active"
            value={draft.enabled}
            trackColor={{ false: '#D7D4CD', true: '#9ED2B8' }}
            thumbColor={draft.enabled ? '#007A3D' : '#F7F6F2'}
            onValueChange={(enabled) => setDraft((value) => ({ ...value, enabled }))}
          />
        </View>

        {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}

        {task ? (
          <View style={styles.secondaryActions}>
            <Pressable accessibilityRole="button" disabled={Boolean(busy)} style={({ pressed }) => [styles.runButton, pressed && styles.pressed]} onPress={run}>
              {busy === 'run' ? <ActivityIndicator color="#007A3D" /> : <Text style={styles.runButtonText}>Run now</Text>}
            </Pressable>
            <Text style={styles.runHelp}>Run the saved task once now to test it.</Text>
            <Pressable accessibilityRole="button" disabled={Boolean(busy)} hitSlop={10} style={({ pressed }) => [styles.deleteButton, pressed && styles.pressed]} onPress={() => onDelete(task)}>
              <Text style={styles.deleteText}>Delete task</Text>
            </Pressable>
          </View>
        ) : null}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: '#F8F7F3' },
  header: { minHeight: 58, paddingHorizontal: 18, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: '#DDDAD2', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: '#FBFBF9' },
  headerSpacer: { width: 34 },
  headerTitle: { color: '#171714', fontSize: 16, fontWeight: '800' },
  headerAction: { color: '#5D5A54', fontSize: 16 },
  primaryAction: { color: '#007A3D', fontWeight: '800' },
  tabs: { alignSelf: 'center', width: '100%', maxWidth: 680, flexDirection: 'row', gap: 4, paddingHorizontal: 20, paddingTop: 12 },
  tab: { flex: 1, minHeight: 44, borderRadius: 12, alignItems: 'center', justifyContent: 'center', backgroundColor: '#EEECE7' },
  tabActive: { backgroundColor: '#DFF0E6' },
  tabLabel: { color: '#5E5A53', fontSize: 13, fontWeight: '700' },
  tabLabelActive: { color: '#006E37' },
  listContent: { padding: 20, paddingBottom: 60, maxWidth: 680, width: '100%', alignSelf: 'center' },
  intro: { flexDirection: 'row', gap: 14, alignItems: 'center', padding: 17, borderRadius: 20, backgroundColor: '#E9F4EE' },
  introCopy: { flex: 1 },
  introTitle: { color: '#163D29', fontSize: 17, fontWeight: '800' },
  introText: { color: '#557064', fontSize: 13, lineHeight: 18, marginTop: 4 },
  loader: { marginTop: 54 },
  taskList: { marginTop: 20, borderRadius: 18, overflow: 'hidden', borderWidth: 1, borderColor: '#E2DFD8' },
  task: { minHeight: 80, flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 15, paddingVertical: 13, backgroundColor: '#FFFFFF', borderBottomWidth: StyleSheet.hairlineWidth, borderColor: '#E2DFD8' },
  statusDot: { width: 9, height: 9, borderRadius: 5, backgroundColor: '#007A3D' },
  statusDotOff: { backgroundColor: '#B9B5AD' },
  taskCopy: { flex: 1 },
  taskName: { color: '#24231F', fontSize: 16, fontWeight: '700' },
  taskCadence: { color: '#77736B', fontSize: 13, marginTop: 3 },
  taskRun: { color: '#6E6A62', fontSize: 11, marginTop: 3 },
  chevron: { color: '#6E6A62', fontSize: 28, fontWeight: '300' },
  empty: { alignItems: 'center', padding: 34, marginTop: 22, borderRadius: 20, borderWidth: 1, borderStyle: 'dashed', borderColor: '#D8D4CB' },
  emptyTitle: { color: '#24231F', fontSize: 17, fontWeight: '800' },
  emptyText: { color: '#6E6A62', fontSize: 13, lineHeight: 19, textAlign: 'center', marginTop: 6 },
  primaryButton: { minHeight: 45, justifyContent: 'center', paddingHorizontal: 20, borderRadius: 23, backgroundColor: '#007A3D', marginTop: 18 },
  primaryButtonText: { color: '#FFFFFF', fontSize: 15, fontWeight: '800' },
  form: { padding: 20, paddingBottom: 70, maxWidth: 680, width: '100%', alignSelf: 'center' },
  botLine: { flexDirection: 'row', alignItems: 'center', gap: 11, marginBottom: 26 },
  botLineText: { color: '#416052', fontSize: 14, fontWeight: '700' },
  label: { color: '#24231F', fontSize: 14, fontWeight: '800', marginTop: 20, marginBottom: 8 },
  input: { minHeight: 50, paddingHorizontal: 14, borderRadius: 14, borderWidth: 1, borderColor: '#DDDAD2', backgroundColor: '#FFFFFF', color: '#24231F', fontSize: 16 },
  promptInput: { minHeight: 126, paddingTop: 13, paddingBottom: 13, lineHeight: 22 },
  frequencyGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 7 },
  frequencyChoice: { minWidth: '47%', flexGrow: 1, minHeight: 42, alignItems: 'center', justifyContent: 'center', borderRadius: 11, backgroundColor: '#E9E7E1' },
  segmentActive: { backgroundColor: '#FFFFFF' },
  segmentText: { color: '#77736B', fontSize: 14, fontWeight: '700' },
  segmentTextActive: { color: '#007A3D' },
  dayRow: { flexDirection: 'row', justifyContent: 'space-between', gap: 5, marginTop: 12 },
  day: { flex: 1, maxWidth: 48, aspectRatio: 1, borderRadius: 24, alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFFFFF', borderWidth: 1, borderColor: '#DDDAD2' },
  dayActive: { backgroundColor: '#007A3D', borderColor: '#007A3D' },
  dayText: { color: '#69665F', fontSize: 13, fontWeight: '800' },
  dayTextActive: { color: '#FFFFFF' },
  help: { color: '#6E6A62', fontSize: 12, lineHeight: 17, marginTop: 6 },
  enabledRow: { flexDirection: 'row', alignItems: 'center', gap: 14, padding: 15, marginTop: 24, borderRadius: 15, backgroundColor: '#FFFFFF', borderWidth: 1, borderColor: '#E2DFD8' },
  enabledCopy: { flex: 1 },
  enabledTitle: { color: '#24231F', fontSize: 15, fontWeight: '700' },
  error: { color: '#A53A32', fontSize: 13, lineHeight: 19, marginTop: 16 },
  secondaryActions: { alignItems: 'center', marginTop: 28 },
  runButton: { minHeight: 48, width: '100%', alignItems: 'center', justifyContent: 'center', borderRadius: 24, backgroundColor: '#E1F1E8' },
  runButtonText: { color: '#007A3D', fontSize: 15, fontWeight: '800' },
  runHelp: { color: '#6E6A62', fontSize: 12, marginTop: 7 },
  deleteButton: { padding: 12, marginTop: 22 },
  deleteText: { color: '#A53A32', fontSize: 14, fontWeight: '700' },
  pressed: { opacity: 0.68 },
});
