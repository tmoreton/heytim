import { lazy, Suspense } from 'react';
import { ActivityIndicator, View } from 'react-native';

import type { FrogBotApi } from '@/lib/api';
import type { ChatOverlay } from '@froggybot/expo-client';
import type {
  Attachment,
  Bootstrap,
  Bot,
  BotDraft,
  CapabilitySelection,
  Group,
  GroupDraft,
  GroupMember,
} from '@froggybot/contracts';

import { styles } from './chat-app.styles';

const AccountSettings = lazy(() => import('./account-settings').then((module) => ({ default: module.AccountSettings })));
const BotDocuments = lazy(() => import('./bot-documents').then((module) => ({ default: module.BotDocuments })));
const BotEditor = lazy(() => import('./bot-editor').then((module) => ({ default: module.BotEditor })));
const BotLibrary = lazy(() => import('./bot-library').then((module) => ({ default: module.BotLibrary })));
const Connections = lazy(() => import('./connections').then((module) => ({ default: module.Connections })));
const GroupEditor = lazy(() => import('./group-editor').then((module) => ({ default: module.GroupEditor })));
const ImagePreviewModal = lazy(() => import('./image-preview-modal').then((module) => ({ default: module.ImagePreviewModal })));
const MemorySettings = lazy(() => import('./memory-settings').then((module) => ({ default: module.MemorySettings })));
const ScheduledTasks = lazy(() => import('./scheduled-tasks').then((module) => ({ default: module.ScheduledTasks })));
const SkillLibrary = lazy(() => import('./skill-library').then((module) => ({ default: module.SkillLibrary })));

type Props = {
  api: FrogBotApi;
  overlay: ChatOverlay;
  data?: Bootstrap;
  demo: boolean;
  editingBot?: Bot;
  selectedGroup?: Group;
  suggestedCapability?: CapabilitySelection;
  botLibraryOpen: boolean;
  botLibraryOnboarding: boolean;
  initialBotTemplateId?: string;
  previewFile?: Attachment;
  onOverlayChange: (overlay: ChatOverlay) => void;
  onDismissBotLibrary: () => void;
  onSaveBot: (value: BotDraft) => Promise<void>;
  onInstallBotTemplate: (templateId: string) => Promise<Bot>;
  onSaveGroup: (value: GroupDraft) => Promise<void>;
  onShareGroup: () => Promise<string>;
  onRemoveGroupMember: (member: GroupMember) => Promise<void>;
  onDeleteGroup: () => Promise<void>;
  onDeleteGroupDecision: (decisionId: string) => Promise<void>;
  onBootstrapChanged: () => Promise<unknown>;
  onOpenCapabilityEditor: (capability: CapabilitySelection) => void;
  onDeleteAccount: () => Promise<void>;
  onSignOut: () => Promise<void>;
  onScheduleTriggered: () => Promise<void>;
  onOpenFile: (file: Attachment) => Promise<void>;
  onClosePreview: () => void;
  onResolveFile: (fileId: string) => Promise<string>;
};

function OverlayLoading() {
  return (
    <View accessibilityLabel="Loading" accessibilityRole="progressbar" style={styles.overlayLoading}>
      <ActivityIndicator color="#007A3D" size="large" />
    </View>
  );
}

export function ChatOverlays({
  api,
  overlay,
  data,
  demo,
  editingBot,
  selectedGroup,
  suggestedCapability,
  botLibraryOpen,
  botLibraryOnboarding,
  initialBotTemplateId,
  previewFile,
  onOverlayChange,
  onDismissBotLibrary,
  onSaveBot,
  onInstallBotTemplate,
  onSaveGroup,
  onShareGroup,
  onRemoveGroupMember,
  onDeleteGroup,
  onDeleteGroupDecision,
  onBootstrapChanged,
  onOpenCapabilityEditor,
  onDeleteAccount,
  onSignOut,
  onScheduleTriggered,
  onOpenFile,
  onClosePreview,
  onResolveFile,
}: Props) {
  const close = () => onOverlayChange({ kind: 'none' });

  return (
    <Suspense fallback={<OverlayLoading />}>
      {overlay.kind === 'botEditor' && data ? (
        <BotEditor
          key={`${overlay.mode}-${editingBot?.id ?? 'new'}-${suggestedCapability?.kind ?? ''}-${suggestedCapability?.id ?? ''}`}
          bot={overlay.mode === 'edit' ? editingBot : undefined}
          constraints={data.constraints}
          tools={data.tools}
          retiredToolIds={data.retiredToolIds ?? []}
          skills={data.skills}
          suggestedCapability={suggestedCapability}
          onClose={close}
          onSave={onSaveBot}
          onLoadSkill={api.skill}
        />
      ) : null}
      {botLibraryOpen && data ? (
        <BotLibrary
          bots={data.bots}
          templates={data.botTemplates ?? []}
          skills={data.skills}
          onboarding={botLibraryOnboarding}
          initialTemplateId={initialBotTemplateId}
          onClose={onDismissBotLibrary}
          onInstall={onInstallBotTemplate}
        />
      ) : null}
      {overlay.kind === 'groupEditor' && data ? (
        <GroupEditor
          key={`${overlay.mode}-${selectedGroup?.id ?? 'new'}`}
          group={overlay.mode === 'edit' ? selectedGroup : undefined}
          constraints={data.constraints}
          bots={data.bots}
          onClose={close}
          onSave={onSaveGroup}
          onShare={onShareGroup}
          onRemoveMember={onRemoveGroupMember}
          onDelete={onDeleteGroup}
          onDeleteDecision={onDeleteGroupDecision}
          onLoadMemory={api.groupMemories}
          onCreateMemory={api.createGroupMemory}
          onUpdateMemory={api.updateGroupMemory}
          onDeleteMemory={api.deleteGroupMemory}
        />
      ) : null}
      {overlay.kind === 'skillLibrary' && data ? (
        <SkillLibrary
          constraints={data.constraints}
          skills={data.skills}
          tools={data.tools}
          onClose={close}
          onLoad={api.skill}
          onSave={api.saveSkill}
          onShare={api.shareSkill}
          onChanged={async () => {
            await onBootstrapChanged();
          }}
          onUse={onOpenCapabilityEditor}
        />
      ) : null}
      {overlay.kind === 'connections' ? (
        <Connections
          tools={data?.tools ?? []}
          providers={data?.connectionProviders ?? []}
          onClose={close}
          onBeginConnection={api.beginConnection}
          onDeleteConnection={api.deleteConnection}
          onChanged={async () => {
            await onBootstrapChanged();
          }}
        />
      ) : null}
      {overlay.kind === 'schedule' && data ? (
        <ScheduledTasks
          bot={overlay.bot}
          constraints={data.constraints}
          onClose={close}
          onList={api.schedules}
          onListRuns={api.scheduleRuns}
          onSave={api.saveSchedule}
          onDelete={api.deleteSchedule}
          onRun={api.runSchedule}
          onApproveRun={(runId) => api.approveMessage(overlay.bot.id, runId)}
          onCancelRun={(runId) => api.cancelMessage(overlay.bot.id, runId)}
          onTriggered={onScheduleTriggered}
        />
      ) : null}
      {overlay.kind === 'groupSchedule' && data ? (
        <ScheduledTasks
          bot={{ id: overlay.group.id, name: overlay.group.name, color: '#58BEAA' }}
          constraints={data.constraints}
          onClose={close}
          onList={api.groupSchedules}
          onListRuns={api.groupScheduleRuns}
          onSave={api.saveGroupSchedule}
          onDelete={api.deleteGroupSchedule}
          onRun={api.runGroupSchedule}
          onTriggered={onScheduleTriggered}
        />
      ) : null}
      {overlay.kind === 'documents' ? (
        <BotDocuments
          bot={overlay.bot}
          onClose={close}
          onList={api.botDocuments}
          onOpen={onOpenFile}
        />
      ) : null}
      {overlay.kind === 'account' ? (
        <AccountSettings
          demo={demo}
          onClose={close}
          onOpenMemory={() => onOverlayChange({ kind: 'memory' })}
          onOpenSkills={() => onOverlayChange({ kind: 'skillLibrary' })}
          onOpenConnections={() => onOverlayChange({ kind: 'connections' })}
          onListShares={api.sharedLinks}
          onRevokeShare={api.revokeShare}
          onDeleteAccount={onDeleteAccount}
          onSignOut={onSignOut}
        />
      ) : null}
      {overlay.kind === 'memory' && data ? (
        <MemorySettings
          maxContentLength={data.constraints.memoryMaxLength}
          onClose={close}
          onLoad={api.memories}
          onCreate={api.createMemory}
          onUpdate={api.updateMemory}
          onDelete={api.deleteMemory}
          onExport={api.exportMemory}
        />
      ) : null}
      {previewFile ? (
        <ImagePreviewModal
          file={previewFile}
          onClose={onClosePreview}
          onResolveFile={onResolveFile}
        />
      ) : null}
    </Suspense>
  );
}
