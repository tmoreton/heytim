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

import type { Invitation } from './types';

export type EmailCodeSession = {
  email: string;
  purpose: 'signIn' | 'signUp';
};

export type EmailCodeStart = EmailCodeSession | { email: string; purpose: 'signedIn' };

export const normalizeEmail = (rawEmail: string): string => {
  const email = rawEmail.trim().toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    throw new Error('Enter a valid email address.');
  }
  return email;
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

const beginSignIn = async (email: string): Promise<EmailCodeStart> => {
  const result = await signIn({
    username: email,
    options: {
      authFlowType: 'USER_AUTH',
      preferredChallenge: 'EMAIL_OTP',
    },
  });

  if (result.isSignedIn) return { email, purpose: 'signedIn' };
  if (result.nextStep.signInStep === 'CONFIRM_SIGN_IN_WITH_EMAIL_CODE') {
    return { email, purpose: 'signIn' };
  }
  throw new Error('Email code sign-in is not available for this account.');
};

const invitationRequired = (): Error =>
  new Error('FroggyBot is invite-only right now. Open a link shared by a member to create your account.');

export const beginEmailCode = async (
  rawEmail: string,
  invitation?: Invitation,
): Promise<EmailCodeStart> => {
  const email = normalizeEmail(rawEmail);

  if (!invitation) {
    try {
      return await beginSignIn(email);
    } catch (value) {
      if (hasErrorName(value, 'UserNotConfirmedException')) {
        await resendSignUpCode({ username: email });
        return { email, purpose: 'signUp' };
      }
      if (hasErrorName(value, 'UserNotFoundException')) throw invitationRequired();
      throw value;
    }
  }

  try {
    const result = await signUp({
      username: email,
      options: {
        userAttributes: { email },
        autoSignIn: { authFlowType: 'USER_AUTH' },
        clientMetadata: {
          inviteKind: invitation.kind,
          inviteToken: invitation.token,
        },
      },
    });

    if (result.nextStep.signUpStep === 'CONFIRM_SIGN_UP') {
      return { email, purpose: 'signUp' };
    }
    return beginSignIn(email);
  } catch (value) {
    if (hasErrorName(value, 'UserLambdaValidationException')) {
      throw new Error('This invitation is no longer valid. Ask a friend for a fresh FroggyBot link.');
    }
    if (!hasErrorName(value, 'UsernameExistsException')) throw value;
  }

  try {
    return await beginSignIn(email);
  } catch (value) {
    if (!hasErrorName(value, 'UserNotConfirmedException')) throw value;
    await resendSignUpCode({ username: email });
    return { email, purpose: 'signUp' };
  }
};

export const finishEmailCode = async (session: EmailCodeSession, code: string): Promise<void> => {
  if (session.purpose === 'signIn') {
    const result = await confirmSignIn({ challengeResponse: code.trim() });
    if (!result.isSignedIn) throw new Error('That code did not work.');
    return;
  }

  const result = await confirmSignUp({
    username: session.email,
    confirmationCode: code.trim(),
  });
  if (result.nextStep.signUpStep !== 'COMPLETE_AUTO_SIGN_IN') {
    throw new Error('Your email is confirmed. Request a new code to sign in.');
  }

  const signedIn = await autoSignIn();
  if (!signedIn.isSignedIn) throw new Error('Your email is confirmed. Request a new code to sign in.');
};

export const endSession = (): Promise<void> => signOut();
