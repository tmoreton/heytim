import 'react-native-get-random-values';

import {
  autoSignIn,
  confirmSignIn,
  confirmSignUp,
  fetchAuthSession,
  resendSignUpCode,
  signIn,
  signOut,
  signUp,
} from 'aws-amplify/auth';

export type PhoneCodeSession = {
  phoneNumber: string;
  purpose: 'signIn' | 'signUp';
};

export type PhoneCodeStart = PhoneCodeSession | { phoneNumber: string; purpose: 'signedIn' };

export const normalizePhoneNumber = (rawPhoneNumber: string): string => {
  const trimmed = rawPhoneNumber.trim();
  const digits = trimmed.replace(/\D/g, '');
  const phoneNumber = trimmed.startsWith('+')
    ? `+${digits}`
    : digits.length === 10
      ? `+1${digits}`
      : digits.length === 11 && digits.startsWith('1')
        ? `+${digits}`
        : '';

  if (!/^\+[1-9]\d{7,14}$/.test(phoneNumber)) {
    throw new Error('Enter a valid phone number, including the country code.');
  }
  return phoneNumber;
};

export const formatPhoneNumber = (phoneNumber: string): string => {
  const match = phoneNumber.match(/^\+1(\d{3})(\d{3})(\d{4})$/);
  return match ? `+1 (${match[1]}) ${match[2]}-${match[3]}` : phoneNumber;
};

export const hasSession = async (): Promise<boolean> => {
  try {
    const session = await fetchAuthSession();
    return Boolean(session.tokens?.idToken);
  } catch {
    return false;
  }
};

const hasErrorName = (value: unknown, name: string): value is Error => value instanceof Error && value.name === name;

const beginSignIn = async (phoneNumber: string): Promise<PhoneCodeStart> => {
  const result = await signIn({
    username: phoneNumber,
    options: {
      authFlowType: 'USER_AUTH',
      preferredChallenge: 'SMS_OTP',
    },
  });

  if (result.isSignedIn) return { phoneNumber, purpose: 'signedIn' };
  if (result.nextStep.signInStep === 'CONFIRM_SIGN_IN_WITH_SMS_CODE') {
    return { phoneNumber, purpose: 'signIn' };
  }
  throw new Error('SMS code sign-in is not available for this account.');
};

export const beginPhoneCode = async (rawPhoneNumber: string): Promise<PhoneCodeStart> => {
  const phoneNumber = normalizePhoneNumber(rawPhoneNumber);

  try {
    const result = await signUp({
      username: phoneNumber,
      options: {
        userAttributes: { phone_number: phoneNumber },
        autoSignIn: { authFlowType: 'USER_AUTH' },
      },
    });

    if (result.nextStep.signUpStep === 'CONFIRM_SIGN_UP') {
      return { phoneNumber, purpose: 'signUp' };
    }
    return beginSignIn(phoneNumber);
  } catch (value) {
    if (!hasErrorName(value, 'UsernameExistsException')) throw value;
  }

  try {
    return await beginSignIn(phoneNumber);
  } catch (value) {
    if (!hasErrorName(value, 'UserNotConfirmedException')) throw value;
    await resendSignUpCode({ username: phoneNumber });
    return { phoneNumber, purpose: 'signUp' };
  }
};

export const finishPhoneCode = async (session: PhoneCodeSession, code: string): Promise<void> => {
  if (session.purpose === 'signIn') {
    const result = await confirmSignIn({ challengeResponse: code.trim() });
    if (!result.isSignedIn) throw new Error('That code did not work.');
    return;
  }

  const result = await confirmSignUp({
    username: session.phoneNumber,
    confirmationCode: code.trim(),
  });
  if (result.nextStep.signUpStep !== 'COMPLETE_AUTO_SIGN_IN') {
    throw new Error('Your phone number is confirmed. Request a new code to sign in.');
  }

  const signedIn = await autoSignIn();
  if (!signedIn.isSignedIn) throw new Error('Your phone number is confirmed. Request a new code to sign in.');
};

export const endSession = (): Promise<void> => signOut();
