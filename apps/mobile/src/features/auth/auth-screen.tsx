import { useRef, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { beginEmailCode, finishEmailCode, type EmailCodeSession } from '@/lib/auth';
import type { Invitation, InvitePreview } from '@/lib/types';

type Props = {
  cloudReady: boolean;
  onSignedIn: () => void;
  onDemo: () => void;
  invitation?: Invitation;
  invitePreview?: InvitePreview;
};

export function AuthScreen({ cloudReady, onSignedIn, onDemo, invitation, invitePreview }: Props) {
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [emailCodeSession, setEmailCodeSession] = useState<EmailCodeSession>();
  const [focusedField, setFocusedField] = useState<'email' | 'code'>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const codeInput = useRef<TextInput>(null);
  const codeSent = Boolean(emailCodeSession);
  const expectedCodeLength = emailCodeSession?.purpose === 'signIn' ? 8 : 6;

  const start = async () => {
    if (!cloudReady) return;
    setBusy(true);
    setError('');
    try {
      const result = await beginEmailCode(email, invitation);
      setEmail(result.email);
      if (result.purpose === 'signedIn') {
        onSignedIn();
        return;
      }
      setEmailCodeSession(result);
      setTimeout(() => codeInput.current?.focus(), 100);
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not send a code.');
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!emailCodeSession || code.length !== expectedCodeLength) {
      setError(`Enter the ${expectedCodeLength}-digit code from your email.`);
      return;
    }
    setBusy(true);
    setError('');
    try {
      await finishEmailCode(emailCodeSession, code);
      onSignedIn();
    } catch (value) {
      setError(value instanceof Error ? value.message : 'That code did not work.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safeArea}>
      <KeyboardAvoidingView style={styles.keyboardAvoider} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView
          bounces={false}
          contentContainerStyle={styles.page}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}>
          <View style={styles.brand}>
            <Image
              accessibilityIgnoresInvertColors
              resizeMode="contain"
              source={require('../../../assets/images/frogbot-foreground.png')}
              style={styles.mark}
            />
            <Text style={styles.name}>FrogBot</Text>
            <Text style={styles.tagline}>Your small team of capable AI coworkers.</Text>
          </View>

          <View style={styles.card}>
            <Text style={styles.eyebrow}>
              {codeSent ? 'ONE LAST STEP' : invitation ? "YOU'RE INVITED" : 'MEMBER SIGN IN'}
            </Text>
            <Text style={styles.cardTitle}>
              {codeSent ? 'Check your messages' : invitePreview ? `Join ${invitePreview.title}` : 'Welcome back'}
            </Text>
            <Text style={styles.cardCopy}>
              {codeSent
                ? `We sent a ${expectedCodeLength}-digit code to ${email}.`
                : invitation
                  ? 'Use your email to accept this invitation. No password needed.'
                  : 'Sign in with your email. New accounts need an invitation from a member.'}
            </Text>

            {!codeSent && invitePreview ? (
              <View style={styles.inviteSummary}>
                <Image
                  accessibilityIgnoresInvertColors
                  resizeMode="contain"
                  source={require('../../../assets/images/frogbot-foreground.png')}
                  style={styles.inviteMark}
                />
                <View style={styles.inviteSummaryText}>
                  <Text numberOfLines={1} style={styles.inviteTitle}>{invitePreview.title}</Text>
                  <Text numberOfLines={1} style={styles.inviteMeta}>
                    {invitePreview.kind === 'group'
                      ? `${invitePreview.peopleCount ?? 1} people · ${invitePreview.bots.length} FrogBots`
                      : invitePreview.description}
                  </Text>
                </View>
              </View>
            ) : null}

            {codeSent ? (
              <View style={styles.fieldGroup}>
                <View style={styles.labelRow}>
                  <Text style={styles.fieldLabel}>Verification code</Text>
                  <Text style={styles.fieldHint}>{expectedCodeLength} digits</Text>
                </View>
                <TextInput
                  ref={codeInput}
                  accessibilityLabel={`${expectedCodeLength}-digit verification code`}
                  style={[styles.input, styles.codeInput, focusedField === 'code' && styles.inputFocused]}
                  value={code}
                  onChangeText={(value) => {
                    setCode(value.replace(/\D/g, '').slice(0, expectedCodeLength));
                    setError('');
                  }}
                  onFocus={() => setFocusedField('code')}
                  onBlur={() => setFocusedField(undefined)}
                  placeholder={'0'.repeat(expectedCodeLength)}
                  placeholderTextColor="#B7B4AC"
                  keyboardType="number-pad"
                  textContentType="oneTimeCode"
                  autoComplete="one-time-code"
                  maxLength={expectedCodeLength}
                  returnKeyType="done"
                  onSubmitEditing={confirm}
                />
              </View>
            ) : (
              <View style={styles.fieldGroup}>
                <Text style={styles.fieldLabel}>Email address</Text>
                <TextInput
                  accessibilityLabel="Email address"
                  style={[styles.input, focusedField === 'email' && styles.inputFocused]}
                  value={email}
                  onChangeText={(value) => {
                    setEmail(value);
                    setError('');
                  }}
                  onFocus={() => setFocusedField('email')}
                  onBlur={() => setFocusedField(undefined)}
                  placeholder="you@example.com"
                  placeholderTextColor="#A6A39C"
                  keyboardType="email-address"
                  textContentType="emailAddress"
                  autoComplete="email"
                  autoCapitalize="none"
                  autoCorrect={false}
                  returnKeyType="go"
                  onSubmitEditing={start}
                />
              </View>
            )}

            {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}

            <Pressable
              accessibilityRole="button"
              accessibilityState={{ busy, disabled: busy || !cloudReady }}
              style={({ pressed }) => [styles.primaryButton, pressed && styles.pressed, busy && styles.disabled]}
              disabled={busy || !cloudReady}
              onPress={codeSent ? confirm : start}>
              {busy ? (
                <ActivityIndicator color="white" />
              ) : (
                <Text style={styles.primaryLabel}>{codeSent ? 'Sign in' : 'Continue'}</Text>
              )}
            </Pressable>

            {codeSent ? (
              <Pressable
                accessibilityRole="button"
                onPress={() => {
                  setEmailCodeSession(undefined);
                  setCode('');
                  setError('');
                }}>
                <Text style={styles.secondaryLabel}>Use a different email address</Text>
              </Pressable>
            ) : null}

            {!cloudReady ? (
              <View style={styles.previewBlock}>
                <Text style={styles.previewCopy}>
                  AWS is not connected yet. You can still explore the finished interface.
                </Text>
                <Pressable accessibilityRole="button" style={styles.previewButton} onPress={onDemo}>
                  <Text style={styles.previewLabel}>Preview the app</Text>
                </Pressable>
              </View>
            ) : null}

            <View style={styles.assurance}>
              <View style={styles.assuranceDot} />
              <Text style={styles.assuranceText}>
                {invitation ? 'This invite unlocks your FrogBot account.' : 'Existing members can always sign back in.'}
              </Text>
            </View>
          </View>

          <Text style={styles.footnote}>By continuing, you agree to use your bots responsibly.</Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: '#F4F2EC' },
  keyboardAvoider: { flex: 1 },
  page: { flexGrow: 1, justifyContent: 'center', paddingHorizontal: 24, paddingVertical: 18 },
  brand: { alignItems: 'center', marginBottom: 32 },
  mark: { width: 84, height: 72, marginBottom: 12 },
  name: { fontSize: 34, fontWeight: '800', letterSpacing: -1.3, color: '#11110F' },
  tagline: { color: '#77736B', fontSize: 16, marginTop: 7, textAlign: 'center' },
  card: {
    alignSelf: 'center',
    width: '100%',
    maxWidth: 420,
    backgroundColor: 'white',
    borderWidth: 1,
    borderColor: '#E7E3DA',
    borderRadius: 26,
    padding: 24,
    ...Platform.select({
      web: { boxShadow: '0 18px 45px rgba(25,24,18,0.07)' },
      default: { shadowColor: '#191812', shadowOpacity: 0.07, shadowRadius: 30, shadowOffset: { width: 0, height: 14 } },
    }),
  },
  eyebrow: { color: '#007A3D', fontSize: 11, fontWeight: '800', letterSpacing: 1.25, marginBottom: 9 },
  cardTitle: { fontSize: 25, fontWeight: '700', color: '#171714', letterSpacing: -0.65 },
  cardCopy: { fontSize: 15, color: '#77736B', lineHeight: 22, marginTop: 7, marginBottom: 22 },
  inviteSummary: { flexDirection: 'row', alignItems: 'center', gap: 12, borderRadius: 16, backgroundColor: '#EAF5EF', borderWidth: 1, borderColor: '#C9E2D4', padding: 12, marginTop: -8, marginBottom: 20 },
  inviteMark: { width: 38, height: 38, borderRadius: 12 },
  inviteSummaryText: { flex: 1, minWidth: 0 },
  inviteTitle: { color: '#154B31', fontSize: 14, fontWeight: '700' },
  inviteMeta: { color: '#56806A', fontSize: 12, marginTop: 2 },
  fieldGroup: { gap: 9 },
  labelRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  fieldLabel: { color: '#37352F', fontSize: 13, fontWeight: '600' },
  fieldHint: { color: '#969188', fontSize: 12 },
  input: {
    minHeight: 56,
    borderWidth: 1,
    borderColor: '#DEDAD1',
    backgroundColor: '#FAF9F6',
    borderRadius: 16,
    paddingHorizontal: 16,
    color: '#171714',
    fontSize: 16,
  },
  inputFocused: { borderColor: '#007A3D', backgroundColor: '#FFFFFF' },
  codeInput: { textAlign: 'center', fontSize: 26, letterSpacing: 9, fontWeight: '600' },
  primaryButton: {
    height: 56,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#007A3D',
    marginTop: 16,
  },
  primaryLabel: { color: 'white', fontSize: 16, fontWeight: '600' },
  secondaryLabel: { textAlign: 'center', color: '#007A3D', fontSize: 14, fontWeight: '600', marginTop: 17 },
  error: { color: '#B83C32', fontSize: 13, lineHeight: 18, marginTop: 10 },
  pressed: { opacity: 0.78 },
  disabled: { opacity: 0.45 },
  previewBlock: { borderTopWidth: 1, borderColor: '#ECE9E2', marginTop: 21, paddingTop: 18 },
  previewCopy: { color: '#77736B', fontSize: 13, lineHeight: 18, textAlign: 'center' },
  previewButton: { alignItems: 'center', paddingTop: 13, paddingBottom: 2 },
  previewLabel: { color: '#007A3D', fontSize: 15, fontWeight: '700' },
  assurance: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 7,
    borderTopWidth: 1,
    borderColor: '#EEEAE2',
    marginTop: 22,
    paddingTop: 18,
  },
  assuranceDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: '#007A3D' },
  assuranceText: { color: '#8A857C', fontSize: 12.5 },
  footnote: { color: '#9B978F', fontSize: 12, textAlign: 'center', marginTop: 22 },
});
