import { ActivityIndicator, Modal, Pressable, ScrollView, Switch, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useModalFocus } from '@/components/use-modal-focus';

import BrowserLiveViewFrame from './browser-live-view-frame';
import { styles } from './browser-handoff.styles';
import type { useBrowserHandoff } from './use-browser-handoff';

type Handoff = ReturnType<typeof useBrowserHandoff>;

export function BrowserHandoffModal({ botName, active, canBrowse, handoff }: { botName: string; active: boolean; canBrowse: boolean; handoff: Handoff }) {
  const insets = useSafeAreaInsets();
  const focus = useModalFocus(handoff.requestClose);
  const { state, busy, expired, confirmation } = handoff;
  const humanControl = state?.status === 'human_control';
  return (
    <Modal visible animationType="fade" transparent onRequestClose={handoff.requestClose}>
      <View style={[styles.backdrop, { paddingTop: insets.top + 8, paddingBottom: insets.bottom + 8 }]}>
        <View ref={focus} accessibilityViewIsModal aria-modal role="dialog" accessibilityLabel={`${botName} private browser`} style={styles.modal}>
          <View style={styles.header}>
            <View style={styles.identity}>
              <Text accessibilityRole="header" style={styles.title}>{botName} browser</Text>
              <Text selectable style={styles.profile}>{state?.contextLabel ?? 'Checking your isolated browser profile…'}</Text>
              <Text style={styles.small}>Private to you and this bot · {state?.hasSavedLogin ? 'Saved login available' : 'No saved login'}</Text>
            </View>
            <Button label="Close" disabled={busy} onPress={handoff.requestClose} />
          </View>
          <ScrollView style={styles.instructions} contentContainerStyle={styles.instructionContent}>
            <Text style={styles.copy}>Open this bot’s browser, enter the website in its address bar if needed, and sign in there. Links opened from chat use a different browser. Never paste passwords or session tokens into chat.</Text>
            {!canBrowse ? <Text style={styles.copy}>The browser tool is no longer enabled. You can still disconnect or forget this bot’s saved login here.</Text> : null}
            <Text style={styles.small}>{humanControl ? 'You have control. The bot cannot browse while you sign in.' : 'The bot must finish or stop its active response before you take control.'} On a small screen, zoom to reach the browser controls.</Text>
            {state?.sessionExpiresAt ? <Text style={styles.small}>Browser session expires {new Date(state.sessionExpiresAt).toLocaleString()}.</Text> : null}
            {handoff.error ? <Text accessibilityRole="alert" style={styles.error}>{handoff.error}</Text> : null}
          </ScrollView>
          <View style={styles.viewer}>
            {state?.liveViewUrl && !busy && !confirmation ? (
              <BrowserLiveViewFrame signedUrl={state.liveViewUrl} />
            ) : (
              <View style={styles.placeholder}>
                {busy ? <ActivityIndicator color="#007A3D" /> : null}
                <Text style={styles.copy}>{state?.status === 'resuming' ? 'Saving your private profile and handing control back to the bot…' : busy ? 'Updating browser…' : expired ? 'The viewing connection expired. Refresh it to keep signing in.' : confirmation ? 'Browser view paused while you confirm.' : active ? 'Wait for the response to finish, or close this dialog and stop it in chat.' : 'Your bot’s private browser will appear here.'}</Text>
                {!busy && !confirmation && canBrowse ? <Button label={humanControl || expired ? 'Refresh connection' : 'Open browser'} disabled={active || state?.status === 'resuming' || !state} onPress={() => void handoff.open()} /> : null}
              </View>
            )}
          </View>
          {confirmation ? (
            <View style={styles.footer}>
              <Text accessibilityRole="header" style={styles.title}>{confirmation === 'forget' ? 'Forget this bot’s saved login?' : 'Disconnect this browser?'}</Text>
              <Text style={styles.copy}>{confirmation === 'forget'
                ? 'Remove the saved browser profile and end this bot’s browser session. Other bots’ profiles stay unchanged. You may need to sign in again.'
                : 'End this browser session without resuming the bot. Unsaved login changes may be lost; an existing saved profile is kept.'}</Text>
              <View style={styles.actions}>
                <Button label="Cancel" disabled={busy} onPress={() => handoff.setConfirmation(undefined)} />
                <Button label={confirmation === 'forget' ? 'Forget login' : 'Disconnect'} disabled={busy} destructive onPress={() => void (confirmation === 'forget' ? handoff.forget() : handoff.disconnect())} />
              </View>
            </View>
          ) : (
            <View style={styles.footer}>
              <View style={styles.remember}>
                <Switch accessibilityLabel="Remember login for this bot only" value={handoff.rememberLogin} disabled={busy || !humanControl} onValueChange={handoff.setRememberLogin} trackColor={{ true: '#007A3D' }} />
                <View style={styles.identity}>
                  <Text style={styles.copy}>Remember login for this bot only</Text>
                  <Text style={styles.small}>Save this browser profile when you resume. The website may still require a future sign-in.</Text>
                </View>
              </View>
              <View style={styles.actions}>
                <Button label="Forget login" disabled={busy || !state?.hasSavedLogin} destructive onPress={() => handoff.setConfirmation('forget')} />
                <Button label="Disconnect" disabled={busy || !state || state.status === 'closed'} onPress={() => handoff.setConfirmation('disconnect')} />
                <Button label="Check status" disabled={busy} onPress={() => void handoff.refreshStatus()} />
                {state?.status === 'resuming' && handoff.pendingConsent !== undefined ? <Button label="Continue handoff" primary disabled={busy} onPress={() => void handoff.resume()} /> : null}
                {state?.liveViewUrl ? <Button label="Refresh connection" disabled={busy} onPress={() => void handoff.open()} /> : null}
                <Button label="Resume bot" primary disabled={busy || active || !canBrowse || !humanControl || !state?.liveViewUrl} onPress={() => void handoff.resume()} />
              </View>
            </View>
          )}
        </View>
      </View>
    </Modal>
  );
}

function Button({ label, onPress, disabled, destructive, primary }: { label: string; onPress: () => void; disabled?: boolean; destructive?: boolean; primary?: boolean }) {
  return <Pressable accessibilityRole="button" accessibilityState={{ disabled: Boolean(disabled) }} disabled={disabled} onPress={onPress} style={[styles.button, primary && styles.primary, disabled && styles.disabled]}>
    <Text style={[styles.buttonText, destructive && styles.error, primary && styles.primaryText]}>{label}</Text>
  </Pressable>;
}
