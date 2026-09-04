import { defineAuth } from '@aws-amplify/backend';

import { preSignUp } from './pre-sign-up/resource';

export const emailCodeMessage = (code: string): string => `
<div style="background:#f4f2ec;padding:32px 16px;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;color:#171714">
  <div style="max-width:480px;margin:0 auto;background:#ffffff;border:1px solid #e7e3da;border-radius:24px;padding:32px">
    <div style="font-size:24px;font-weight:800;letter-spacing:-0.6px;color:#007a3d">FrogBot</div>
    <h1 style="font-size:24px;line-height:1.25;margin:28px 0 8px">Your sign-in code</h1>
    <p style="font-size:15px;line-height:1.6;color:#77736b;margin:0 0 24px">Use this verification code to continue. It expires shortly.</p>
    <div style="background:#f4f2ec;border-radius:16px;padding:18px;text-align:center;font-size:30px;font-weight:700;letter-spacing:8px;color:#11110f">${code}</div>
    <p style="font-size:12px;line-height:1.5;color:#969188;margin:24px 0 0">If you did not request this code, you can safely ignore this email.</p>
  </div>
</div>`;

export const auth = defineAuth({
  triggers: { preSignUp },
  loginWith: {
    email: {
      otpLogin: true,
      verificationEmailStyle: 'CODE',
      verificationEmailSubject: 'Your FrogBot verification code',
      verificationEmailBody: (createCode) => emailCodeMessage(createCode()),
    },
  },
  // Cognito only allows a custom passwordless email-OTP template when MFA is
  // OPTIONAL. Users are not prompted for MFA unless they explicitly enable it.
  multifactor: {
    mode: 'OPTIONAL',
    email: true,
  },
  // Passwordless users have no password to recover, and Cognito does not allow
  // email to be both the sole recovery method and an email-MFA destination.
  accountRecovery: 'NONE',
  senders: {
    email: {
      fromEmail: 'no-reply@inboxai.cc',
      fromName: 'FrogBot',
    },
  },
});
