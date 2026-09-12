import { useState } from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, Switch, Text, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useModalFocus } from '@/components/use-modal-focus';

import BrowserLiveViewFrame from './browser-live-view-frame';
import { styles } from './browser-handoff.styles';
import type { useBrowserHandoff } from '@froggybot/expo-client/use-browser-handoff';

type Handoff = ReturnType<typeof useBrowserHandoff>;

export function BrowserHandoffModal({ botName, active, canBrowse, handoff }: { botName: string; active: boolean; canBrowse: boolean; handoff: Handoff }) {
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const compact = width < 700;
  const [more, setMore] = useState(false);
  const focus = useModalFocus(handoff.requestClose);
  const { state, busy, expired, confirmation } = handoff;
  const humanControl = state?.status === 'human_control';
  const incomplete = state?.status === 'opening' || state?.status === 'resuming';
  const needsRecovery = Boolean(state?.recoveryRequired);
  const canOpen = !busy && !active && canBrowse && !!state && !incomplete;
  return (
    <Modal visible animationType="fade" transparent onRequestClose={handoff.requestClose}>
      <View style={[styles.backdrop, compact && styles.mobileBackdrop, { paddingTop: insets.top + (compact ? 0 : 8), paddingBottom: insets.bottom + (compact ? 0 : 8) }]}>
        <View ref={focus} accessibilityViewIsModal aria-modal role="dialog" accessibilityLabel={`${botName} private browser`} style={[styles.modal, compact && styles.mobileModal]}>
          <View style={styles.header}>
            <View style={styles.identity}>
              <Text accessibilityRole="header" numberOfLines={1} style={styles.title}>{botName}</Text>
              <Text style={styles.small}>{humanControl ? 'You’re in control' : 'Private bot browser'}{state?.display === 'mobile' ? ' · Mobile' : ''}</Text>
            </View>
            <Pressable accessibilityRole="button" accessibilityLabel="Browser options" accessibilityState={{ expanded: more }} onPress={() => setMore(!more)} style={styles.button}><Text style={styles.buttonText}>{more ? 'Less' : 'More'}</Text></Pressable>
            <Button label="Close" disabled={busy} onPress={handoff.requestClose} />
          </View>
          {handoff.error ? <Text accessibilityRole="alert" style={[styles.error, styles.notice]}>{handoff.error}</Text> : null}
          {humanControl && compact && state.display === 'mobile' && (state.mobileSiteSupported === false || (state.viewport?.width ?? 1440) > 700) ? <Text style={[styles.copy, styles.notice]}>This older or desktop session needs reopening for full mobile support. Save any login with More → Remember login → Resume bot before disconnecting.</Text> : null}
          {!canBrowse ? <Text style={[styles.copy, styles.notice]}>The browser tool is no longer enabled. Enable it in this bot’s tools to open chat links here.</Text> : null}
          {more && !confirmation ? <ScrollView style={styles.options} contentContainerStyle={styles.instructionContent}>
            <Text style={styles.copy}>Sign in here so this bot can use the same session. Never paste passwords or session tokens in chat.</Text>
            <Text style={styles.small}>Private to you and this bot · {state?.hasSavedLogin ? 'Saved login available' : 'No saved login'}</Text>
            <View style={styles.remember}>
              <Switch accessibilityLabel="Remember login for this bot only" value={handoff.rememberLogin} disabled={busy || !humanControl} onValueChange={handoff.setRememberLogin} trackColor={{ true: '#007A3D' }} />
              <View style={styles.identity}><Text style={styles.copy}>Remember login for this bot</Text><Text style={styles.small}>Save this profile when you resume. Off by default.</Text></View>
            </View>
            <View style={styles.actions}>
              {humanControl ? <Button label={state?.display === 'mobile' ? 'Request desktop site' : 'Request mobile site'} disabled={!canOpen} onPress={() => { setMore(false); void handoff.open({ display: state?.display === 'mobile' ? 'desktop' : 'mobile' }); }} /> : null}
              {state?.liveViewUrl ? <Button label="Refresh connection" disabled={!canOpen} onPress={() => { setMore(false); void handoff.open(); }} /> : null}
              <Button label="Check status" disabled={busy} onPress={() => void handoff.refreshStatus()} />
              {state && state.status !== 'closed' ? <Button label="Disconnect" disabled={busy} onPress={() => handoff.setConfirmation('disconnect')} /> : null}
              {state?.hasSavedLogin ? <Button label="Forget login" disabled={busy} destructive onPress={() => handoff.setConfirmation('forget')} /> : null}
            </View>
          </ScrollView> : null}
          <View style={styles.viewer}>
            {state?.liveViewUrl && !busy && !confirmation ? (
              <BrowserLiveViewFrame signedUrl={state.liveViewUrl} viewport={state.viewport} />
            ) : (
              <View style={styles.placeholder}>
                {busy ? <ActivityIndicator color="#007A3D" /> : null}
                <Text style={styles.copy}>{confirmation ? 'Browser paused while you confirm.' : state?.status === 'resuming' && handoff.pendingConsent !== undefined ? 'Saving your login and resuming the bot…' : busy ? 'Connecting…' : needsRecovery ? 'The last browser connection did not finish.' : state?.status === 'resuming' ? 'Browser handoff is pending.' : state?.status === 'opening' ? 'Browser connection is pending.' : expired ? 'The viewing connection expired. Refresh to reconnect.' : active ? 'The bot is working. Wait or stop it in chat.' : 'Open your bot’s private browser.'}</Text>
                {!busy && !confirmation && incomplete ? <Button label={needsRecovery && handoff.pendingConsent === undefined ? 'Disconnect' : 'Check status'} onPress={() => needsRecovery && handoff.pendingConsent === undefined ? handoff.setConfirmation('disconnect') : void handoff.refreshStatus()} /> : null}
                {!busy && !confirmation && !incomplete && canBrowse ? <Button label={humanControl || expired ? 'Refresh connection' : 'Open browser'} disabled={!canOpen} onPress={() => void handoff.open()} /> : null}
              </View>
            )}
          </View>
          {confirmation ? (
            <View style={styles.footer}>
              <Text accessibilityRole="header" style={styles.title}>{confirmation === 'forget' ? 'Forget this bot’s saved login?' : 'Disconnect this browser?'}</Text>
              <Text style={styles.copy}>{confirmation === 'forget' ? 'Remove this bot’s saved profile and end its browser session. Other bots are unaffected.' : 'End this session without resuming the bot. Unsaved login changes may be lost.'}</Text>
              <View style={styles.actions}>
                <Button label="Cancel" disabled={busy} onPress={() => handoff.setConfirmation(undefined)} />
                <Button label={confirmation === 'forget' ? 'Forget login' : 'Disconnect'} disabled={busy} destructive onPress={() => void (confirmation === 'forget' ? handoff.forget() : handoff.disconnect())} />
              </View>
            </View>
          ) : humanControl || state?.status === 'resuming' ? (
            <View style={[styles.footer, styles.resumeBar]}>
              <Text style={[styles.small, styles.identity]}>{handoff.rememberLogin ? 'Save login on resume' : 'Don’t save new logins'} · More to change</Text>
              {state?.status === 'resuming' && handoff.pendingConsent !== undefined
                ? <Button label="Continue handoff" primary disabled={busy} onPress={() => void handoff.resume()} />
                : <Button label="Resume bot" primary disabled={busy || active || !canBrowse || !state?.liveViewUrl} onPress={() => void handoff.resume()} />}
            </View>
          ) : null}
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
