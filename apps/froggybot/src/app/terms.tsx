import { LegalPage } from '@/features/marketing/legal-page';

const sections = [
  {
    title: 'Using FroggyBot',
    paragraphs: [
      'FroggyBot provides AI assistants that can respond to messages and use the tools and skills you enable. You are responsible for the instructions, content, and integrations you provide and for using the service lawfully.',
      'You must not use FroggyBot to violate another person’s rights, distribute unlawful or harmful material, gain unauthorized access to systems, or misrepresent automated output as verified professional advice.',
    ],
  },
  {
    title: 'Accounts and security',
    paragraphs: [
      'You are responsible for access to your email account and devices used to sign in. Tell us promptly through the support contact in FroggyBot’s App Store listing if you believe your account has been accessed without permission.',
    ],
  },
  {
    title: 'Your content and shared links',
    paragraphs: [
      'You keep your rights in content you submit. You allow FroggyBot and its service providers to process that content only as needed to operate, secure, and improve the service.',
      'When you create a share link, you choose to make the included bot configuration or conversation available to anyone who receives that link. Do not share confidential information unless you intend the recipient to receive it.',
    ],
  },
  {
    title: 'AI output',
    paragraphs: [
      'AI systems can make mistakes or produce incomplete results. Review important output before relying on it, especially for legal, medical, financial, safety, or other high-impact decisions.',
    ],
  },
  {
    title: 'Availability and changes',
    paragraphs: [
      'We may modify, suspend, or discontinue features and may restrict access needed to protect users or the service. FroggyBot is provided on an as-available basis to the extent permitted by law.',
      'We may update these terms as FroggyBot evolves. Continued use after an updated effective date means you accept the revised terms.',
    ],
  },
];

export default function TermsPage() {
  return (
    <LegalPage
      title="Terms of Use"
      description="These terms set the basic rules for using FroggyBot and its AI teammates."
      sections={sections}
    />
  );
}
