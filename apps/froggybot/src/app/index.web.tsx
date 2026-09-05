import { Link, type Href } from 'expo-router';
import Head from 'expo-router/head';
import { useSyncExternalStore } from 'react';
import { Image, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

const frog = require('../../assets/images/frogbot-foreground.png');

const teammates = [
  { name: 'Lake house weekend', note: '4 people · 2 FroggyBots', active: true },
  { name: 'Family plans', note: 'Shared memory updated' },
  { name: 'Book club', note: 'Next meeting confirmed' },
];

const narrowLayoutQuery = '(max-width: 719px)';

function subscribeToNarrowLayout(onChange: () => void) {
  const mediaQuery = window.matchMedia(narrowLayoutQuery);
  mediaQuery.addEventListener('change', onChange);
  return () => mediaQuery.removeEventListener('change', onChange);
}

function getNarrowLayoutSnapshot() {
  return window.matchMedia(narrowLayoutQuery).matches;
}

function getServerLayoutSnapshot() {
  return false;
}

export default function LandingPage() {
  const isNarrow = useSyncExternalStore(
    subscribeToNarrowLayout,
    getNarrowLayoutSnapshot,
    getServerLayoutSnapshot,
  );
  const primaryButtonStyle = StyleSheet.flatten([
    styles.primaryButton,
    isNarrow && styles.primaryButtonNarrow,
  ]);

  return (
    <>
      <Head>
        <title>FroggyBot — Turn group talk into action</title>
        <meta
          name="description"
          content="Invite people with one link, keep editable group memory, and turn conversations into itineraries, budgets, lists, and polished files."
        />
        <meta property="og:title" content="FroggyBot — Turn group talk into action" />
        <meta
          property="og:description"
          content="The AI that helps your group decide, organize, and follow through."
        />
        <meta name="theme-color" content="#F4F2EC" />
      </Head>
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.page}
        showsVerticalScrollIndicator={false}>
        <View style={[styles.header, isNarrow && styles.headerNarrow]}>
          <View style={styles.wordmark}>
            <Image accessibilityIgnoresInvertColors source={frog} resizeMode="contain" style={styles.logo} />
            {!isNarrow ? <Text style={styles.brandName}>FroggyBot</Text> : null}
          </View>
          <View style={styles.headerActions}>
            <Link href={'/library' as Href} style={styles.libraryLink}>Skills & tools</Link>
            <Link href="/app" asChild>
              <Pressable accessibilityRole="link" style={styles.loginButton}>
                <Text style={styles.loginLabel}>Member login</Text>
              </Pressable>
            </Link>
          </View>
        </View>

        <View style={[styles.hero, isNarrow && styles.heroNarrow]}>
          <View style={[styles.heroCopy, isNarrow && styles.heroCopyNarrow]}>
            <View style={styles.eyebrowPill}>
              <View style={styles.eyebrowDot} />
              <Text style={styles.eyebrow}>AI FOR REAL GROUPS</Text>
            </View>
            <Text accessibilityRole="header" style={[styles.title, isNarrow && styles.titleNarrow]}>
              Turn group talk into a plan everyone can use.
            </Text>
            <Text style={[styles.subtitle, isNarrow && styles.subtitleNarrow]}>
              Invite people with one link, keep the group’s memory editable, and let FroggyBot turn decisions into
              itineraries, budgets, checklists, PDFs, and more.
            </Text>
            <View style={[styles.actions, isNarrow && styles.actionsNarrow]}>
              <Link href="/app" asChild>
                <Pressable accessibilityRole="link" style={primaryButtonStyle}>
                  <Text style={styles.primaryLabel}>Member login</Text>
                  <Text style={styles.primaryArrow}>→</Text>
                </Pressable>
              </Link>
              <Text style={[styles.passwordless, isNarrow && styles.passwordlessNarrow]}>
                New here? Ask a member for an invite.
              </Text>
            </View>
          </View>

          <View style={[styles.previewFrame, isNarrow && styles.previewFrameNarrow]}>
            <View style={styles.previewTop}>
              <View style={styles.windowDots}>
                <View style={[styles.windowDot, styles.windowRed]} />
                <View style={[styles.windowDot, styles.windowGold]} />
                <View style={[styles.windowDot, styles.windowGreen]} />
              </View>
              <Text style={styles.previewWordmark}>FroggyBot</Text>
              <View style={styles.previewStatus} />
            </View>
            <View style={styles.previewBody}>
              <View style={styles.previewSidebar}>
                <Text style={styles.teamLabel}>YOUR GROUPS</Text>
                {teammates.map((teammate) => (
                  <View key={teammate.name} style={[styles.botRow, teammate.active && styles.botRowActive]}>
                    <Image source={frog} resizeMode="contain" style={styles.botAvatar} />
                    <View style={styles.botText}>
                      <Text numberOfLines={1} style={styles.botName}>{teammate.name}</Text>
                      <Text numberOfLines={1} style={styles.botNote}>
                        {teammate.note}
                      </Text>
                    </View>
                  </View>
                ))}
              </View>
              <View style={styles.previewChat}>
                <View style={styles.chatIdentity}>
                  <Image source={frog} resizeMode="contain" style={styles.chatAvatar} />
                  <View>
                    <Text style={styles.chatName}>Lake house weekend</Text>
                    <Text style={styles.chatStatus}>4 people · 2 FroggyBots</Text>
                  </View>
                </View>
                <View style={styles.messages}>
                  <View style={styles.assistantBubble}>
                    <Text style={styles.messageText}>I combined everyone’s dates and preferences into two workable weekends.</Text>
                  </View>
                  <View style={styles.userBubble}>
                    <Text style={styles.userMessage}>Use the first one. Make the itinerary and shared budget.</Text>
                  </View>
                  <View style={[styles.assistantBubble, styles.shortBubble]}>
                    <Text style={styles.messageText}>Done — the itinerary PDF and budget spreadsheet are ready for everyone.</Text>
                  </View>
                </View>
                <View style={styles.composer}>
                  <Text style={styles.composerText}>Message the group</Text>
                  <View style={styles.sendButton}>
                    <Text style={styles.sendArrow}>↑</Text>
                  </View>
                </View>
              </View>
            </View>
          </View>
        </View>

        <View style={[styles.features, isNarrow && styles.featuresNarrow]}>
          <Feature number="01" title="Group-scoped memory" copy="Keep goals, preferences, and decisions visible and owner-editable." />
          <Feature number="02" title="One-link participation" copy="Invite someone with one clean link and no password to remember." />
          <Feature number="03" title="Files made for everyone" copy="Turn plans into itineraries, budgets, lists, PDFs, Word files, or spreadsheets." />
          <Feature number="04" title="People stay central" copy="FroggyBots help the group reach an outcome without taking over the conversation." />
        </View>

        <View style={[styles.footer, isNarrow && styles.footerNarrow]}>
          <Text style={styles.footerText}>© 2026 FroggyBot</Text>
          <View style={styles.footerLinks}>
            <Link href="/privacy" style={styles.footerLink}>
              Privacy
            </Link>
            <Link href="/terms" style={styles.footerLink}>
              Terms
            </Link>
            <Link href={'/library' as Href} style={styles.footerLink}>
              Skills & tools
            </Link>
            <Link href="/app" style={styles.footerLink}>
              Member login
            </Link>
          </View>
        </View>
      </ScrollView>
    </>
  );
}

function Feature({ number, title, copy }: { number: string; title: string; copy: string }) {
  return (
    <View style={styles.feature}>
      <Text style={styles.featureNumber}>{number}</Text>
      <Text style={styles.featureTitle}>{title}</Text>
      <Text style={styles.featureCopy}>{copy}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1, backgroundColor: '#F4F2EC' },
  page: { width: '100%', minHeight: '100%', backgroundColor: '#F4F2EC' },
  header: {
    width: '100%',
    maxWidth: 1240,
    alignSelf: 'center',
    paddingHorizontal: 24,
    paddingVertical: 24,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  headerNarrow: { paddingHorizontal: 20, paddingVertical: 20 },
  wordmark: { flexDirection: 'row', alignItems: 'center', gap: 9 },
  logo: { width: 36, height: 31 },
  brandName: { color: '#13130F', fontSize: 21, fontWeight: '800', letterSpacing: -0.55 },
  headerActions: { flexDirection: 'row', alignItems: 'center', gap: 18 },
  libraryLink: { color: '#5E5A52', fontSize: 13, fontWeight: '700' },
  loginButton: {
    height: 42,
    paddingHorizontal: 18,
    borderRadius: 21,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: '#CECBC2',
    backgroundColor: 'rgba(255,255,255,0.5)',
  },
  loginLabel: { color: '#22211D', fontSize: 14, fontWeight: '700' },
  hero: { width: '100%', maxWidth: 1240, alignSelf: 'center', paddingHorizontal: 24, paddingTop: 58, paddingBottom: 70, flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 56 },
  heroNarrow: { paddingHorizontal: 20, paddingTop: 40, paddingBottom: 52, flexDirection: 'column', flexWrap: 'nowrap', alignItems: 'stretch', gap: 40 },
  heroCopy: { flexGrow: 1, flexShrink: 1, flexBasis: 430, minWidth: 0, maxWidth: 570 },
  heroCopyNarrow: { width: '100%', maxWidth: '100%', flexBasis: 'auto', flexGrow: 0 },
  eyebrowPill: { flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start', gap: 8, marginBottom: 20 },
  eyebrowDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: '#007A3D' },
  eyebrow: { color: '#007A3D', fontSize: 11, fontWeight: '800', letterSpacing: 1.4 },
  title: { color: '#13130F', fontSize: 52, lineHeight: 55, fontWeight: '800', letterSpacing: -2.5 },
  titleNarrow: { fontSize: 40, lineHeight: 43, letterSpacing: -1.8 },
  subtitle: { color: '#656158', fontSize: 19, lineHeight: 29, marginTop: 24, maxWidth: 540 },
  subtitleNarrow: { fontSize: 17, lineHeight: 26, marginTop: 20 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 18, marginTop: 32 },
  actionsNarrow: { width: '100%', flexDirection: 'column', flexWrap: 'nowrap', alignItems: 'stretch', gap: 12, marginTop: 28 },
  primaryButton: {
    height: 56,
    paddingHorizontal: 24,
    borderRadius: 28,
    backgroundColor: '#007A3D',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 18,
  },
  primaryButtonNarrow: { width: '100%' },
  primaryLabel: { color: 'white', fontSize: 16, fontWeight: '700' },
  primaryArrow: { color: 'white', fontSize: 20, marginTop: -2 },
  passwordless: { color: '#817D74', fontSize: 13 },
  passwordlessNarrow: { textAlign: 'center' },
  previewFrame: {
    flexGrow: 1,
    flexShrink: 1,
    flexBasis: 500,
    width: '100%',
    maxWidth: 650,
    minHeight: 470,
    backgroundColor: '#FBFBF9',
    borderWidth: 1,
    borderColor: '#D9D6CD',
    borderRadius: 28,
    overflow: 'hidden',
    boxShadow: '0 30px 70px rgba(45, 55, 45, 0.13)',
  },
  previewFrameNarrow: { flexBasis: 'auto', flexGrow: 0, maxWidth: '100%', minHeight: 430 },
  previewTop: {
    height: 48,
    borderBottomWidth: 1,
    borderColor: '#E2DFD7',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
  },
  windowDots: { flexDirection: 'row', gap: 6 },
  windowDot: { width: 8, height: 8, borderRadius: 4 },
  windowRed: { backgroundColor: '#ED6A5E' },
  windowGold: { backgroundColor: '#F3BF4F' },
  windowGreen: { backgroundColor: '#61C554' },
  previewWordmark: { color: '#3E3C36', fontSize: 12, fontWeight: '700' },
  previewStatus: { width: 8, height: 8, borderRadius: 4, backgroundColor: '#007A3D' },
  previewBody: { flex: 1, flexDirection: 'row' },
  previewSidebar: { width: '31%', minWidth: 70, maxWidth: 205, backgroundColor: '#F0EFEB', borderRightWidth: 1, borderColor: '#DFDCD4', padding: 10 },
  teamLabel: { color: '#9A968D', fontSize: 9, fontWeight: '800', letterSpacing: 1.15, marginHorizontal: 8, marginVertical: 11 },
  botRow: { minHeight: 64, borderRadius: 14, flexDirection: 'row', alignItems: 'center', gap: 9, paddingHorizontal: 8 },
  botRowActive: { backgroundColor: '#E0EEE6' },
  botAvatar: { width: 35, height: 31 },
  botText: { flex: 1, minWidth: 0 },
  botName: { color: '#2A2924', fontSize: 13, fontWeight: '700' },
  botNote: { color: '#8B877F', fontSize: 10, marginTop: 3 },
  previewChat: { flex: 1, backgroundColor: '#FBFBF9' },
  chatIdentity: { height: 58, borderBottomWidth: 1, borderColor: '#E4E1D9', flexDirection: 'row', alignItems: 'center', gap: 9, paddingHorizontal: 15 },
  chatAvatar: { width: 29, height: 25 },
  chatName: { color: '#24231E', fontSize: 13, fontWeight: '700' },
  chatStatus: { color: '#007A3D', fontSize: 9, marginTop: 1 },
  messages: { flex: 1, padding: 17, justifyContent: 'center', gap: 10 },
  assistantBubble: { alignSelf: 'flex-start', backgroundColor: '#EEEEEA', borderRadius: 16, borderTopLeftRadius: 5, paddingHorizontal: 13, paddingVertical: 10, maxWidth: '86%' },
  shortBubble: { maxWidth: '72%' },
  userBubble: { alignSelf: 'flex-end', backgroundColor: '#007A3D', borderRadius: 16, borderBottomRightRadius: 5, paddingHorizontal: 13, paddingVertical: 10, maxWidth: '82%' },
  messageText: { color: '#383630', fontSize: 12, lineHeight: 17 },
  userMessage: { color: 'white', fontSize: 12, lineHeight: 17 },
  composer: { height: 49, margin: 12, marginTop: 0, borderWidth: 1, borderColor: '#DCD9D1', borderRadius: 19, backgroundColor: 'white', flexDirection: 'row', alignItems: 'center', paddingLeft: 14, paddingRight: 5 },
  composerText: { flex: 1, color: '#A09C93', fontSize: 11 },
  sendButton: { width: 37, height: 37, borderRadius: 19, backgroundColor: '#007A3D', alignItems: 'center', justifyContent: 'center' },
  sendArrow: { color: 'white', fontSize: 20, fontWeight: '700', marginTop: -3 },
  features: { width: '100%', maxWidth: 1172, alignSelf: 'center', flexDirection: 'row', flexWrap: 'wrap', paddingHorizontal: 24, paddingBottom: 70, gap: 18 },
  featuresNarrow: { paddingHorizontal: 20, paddingBottom: 52 },
  feature: { flexGrow: 1, flexShrink: 1, flexBasis: 250, minHeight: 164, borderTopWidth: 1, borderColor: '#CAC6BC', paddingTop: 18, paddingRight: 20 },
  featureNumber: { color: '#007A3D', fontSize: 11, fontWeight: '800', letterSpacing: 1 },
  featureTitle: { color: '#22211C', fontSize: 18, fontWeight: '700', marginTop: 25 },
  featureCopy: { color: '#77736A', fontSize: 14, lineHeight: 21, marginTop: 7, maxWidth: 270 },
  footer: { width: '100%', maxWidth: 1172, alignSelf: 'center', borderTopWidth: 1, borderColor: '#D4D0C7', paddingHorizontal: 24, paddingVertical: 28, flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 16 },
  footerNarrow: { paddingHorizontal: 20, alignItems: 'flex-start' },
  footerText: { color: '#8A867D', fontSize: 12 },
  footerLinks: { flexDirection: 'row', gap: 20 },
  footerLink: { color: '#5F5B53', fontSize: 12, fontWeight: '600' },
});
