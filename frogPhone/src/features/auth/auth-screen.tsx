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

import { beginPhoneCode, finishPhoneCode, formatPhoneNumber, type PhoneCodeSession } from '@/lib/auth';

type Props = {
  cloudReady: boolean;
  onSignedIn: () => void;
  onDemo: () => void;
};

export function AuthScreen({ cloudReady, onSignedIn, onDemo }: Props) {
  const [phoneNumber, setPhoneNumber] = useState('');
  const [code, setCode] = useState('');
  const [phoneCodeSession, setPhoneCodeSession] = useState<PhoneCodeSession>();
  const [focusedField, setFocusedField] = useState<'phone' | 'code'>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const codeInput = useRef<TextInput>(null);
  const codeSent = Boolean(phoneCodeSession);

  const start = async () => {
    if (!cloudReady) return;
    setBusy(true);
    setError('');
    try {
      const result = await beginPhoneCode(phoneNumber);
      setPhoneNumber(result.phoneNumber);
      if (result.purpose === 'signedIn') {
        onSignedIn();
        return;
      }
      setPhoneCodeSession(result);
      setTimeout(() => codeInput.current?.focus(), 100);
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Could not send a code.');
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!phoneCodeSession || code.length !== 6) {
      setError('Enter the six-digit code from your text message.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await finishPhoneCode(phoneCodeSession, code);
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
            <Text style={styles.eyebrow}>{codeSent ? 'ONE LAST STEP' : 'PASSWORDLESS SIGN IN'}</Text>
            <Text style={styles.cardTitle}>{codeSent ? 'Check your messages' : 'Welcome back'}</Text>
            <Text style={styles.cardCopy}>
              {codeSent
                ? `We sent a six-digit code to ${formatPhoneNumber(phoneNumber)}.`
                : 'Enter your phone number. No password needed.'}
            </Text>

            {codeSent ? (
              <View style={styles.fieldGroup}>
                <View style={styles.labelRow}>
                  <Text style={styles.fieldLabel}>Verification code</Text>
                  <Text style={styles.fieldHint}>6 digits</Text>
                </View>
                <TextInput
                  ref={codeInput}
                  accessibilityLabel="Six-digit verification code"
                  style={[styles.input, styles.codeInput, focusedField === 'code' && styles.inputFocused]}
                  value={code}
                  onChangeText={(value) => {
                    setCode(value.replace(/\D/g, '').slice(0, 6));
                    setError('');
                  }}
                  onFocus={() => setFocusedField('code')}
                  onBlur={() => setFocusedField(undefined)}
                  placeholder="000000"
                  placeholderTextColor="#B7B4AC"
                  keyboardType="number-pad"
                  textContentType="oneTimeCode"
                  autoComplete="one-time-code"
                  maxLength={6}
                />
              </View>
            ) : (
              <View style={styles.fieldGroup}>
                <Text style={styles.fieldLabel}>Phone number</Text>
                <TextInput
                  accessibilityLabel="Phone number"
                  style={[styles.input, focusedField === 'phone' && styles.inputFocused]}
                  value={phoneNumber}
                  onChangeText={(value) => {
                    setPhoneNumber(value);
                    setError('');
                  }}
                  onFocus={() => setFocusedField('phone')}
                  onBlur={() => setFocusedField(undefined)}
                  placeholder="+1 555 123 4567"
                  placeholderTextColor="#A6A39C"
                  keyboardType="phone-pad"
                  textContentType="telephoneNumber"
                  autoComplete="tel"
                  autoCapitalize="none"
                  autoCorrect={false}
                  returnKeyType="go"
                  onSubmitEditing={start}
                />
              </View>
            )}

            {error ? <Text style={styles.error}>{error}</Text> : null}

            <Pressable
              accessibilityRole="button"
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
                  setPhoneCodeSession(undefined);
                  setCode('');
                  setError('');
                }}>
                <Text style={styles.secondaryLabel}>Use a different phone number</Text>
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
              <Text style={styles.assuranceText}>A private SMS code. Nothing to remember.</Text>
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
