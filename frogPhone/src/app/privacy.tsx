import { LegalPage } from '@/features/marketing/legal-page';

const sections = [
  {
    title: 'Information we collect',
    paragraphs: [
      'We collect the email address you use for passwordless authentication, the bot configurations you create, your conversation messages, and basic service records needed to operate and secure FrogBot.',
      'If you allow reply notifications, we store a device push token so we can notify that device when an agent has finished responding. On supported Apple devices, dictation is requested as on-device speech recognition; FrogBot does not intentionally upload or retain the audio recording.',
    ],
  },
  {
    title: 'How we use information',
    paragraphs: [
      'We use this information to authenticate you, save your bots and conversations, run the agents you ask to use, deliver requested notifications, prevent abuse, and maintain the service.',
      'We do not sell personal information. We do not use SMS consent or opt-in data for advertising, and we do not share that consent with third parties for their marketing or promotional purposes.',
    ],
  },
  {
    title: 'Service providers and sharing',
    paragraphs: [
      'FrogBot uses service providers, including Amazon Web Services and Expo, to host authentication, agent processing, data storage, app updates, and notifications. They process information only as needed to provide those services.',
      'A bot or conversation is shared only when you intentionally create a share link. Anyone with a valid link may be able to import the shared content, so share links should be treated as private.',
    ],
  },
  {
    title: 'Retention and choices',
    paragraphs: [
      'We retain account content while it is needed to provide FrogBot, comply with legal obligations, resolve disputes, or protect the service. You can stop notifications in device settings and sign out at any time.',
      'You may request access to or deletion of your account information using the support contact shown in FrogBot’s App Store listing.',
    ],
  },
  {
    title: 'Security, children, and changes',
    paragraphs: [
      'We use administrative and technical safeguards designed to protect information, but no online service can guarantee absolute security. FrogBot is not directed to children under 13.',
      'We may update this policy as the service changes. The effective date at the top will identify the current version.',
    ],
  },
];

export default function PrivacyPage() {
  return (
    <LegalPage
      title="Privacy Policy"
      description="This policy explains what FrogBot collects, why we use it, and the choices available to you."
      sections={sections}
    />
  );
}
