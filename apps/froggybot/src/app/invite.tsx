import { useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import { Link, useLocalSearchParams } from 'expo-router';
import Head from 'expo-router/head';
import { ActivityIndicator, Image, Linking, Platform, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { BotAvatar } from '@/components/bot-avatar';
import { AppEntry } from '@/features/app/app-entry';
import { createApi } from '@/lib/api';
import type { Invitation, InviteKind, InvitePreview } from '@/lib/types';

const frog = require('../../assets/images/frogbot-foreground.png');
const inviteKinds = new Set<InviteKind>(['bot', 'chat', 'group', 'skill']);
const subscribeToHydration = () => () => {};
const getClientSnapshot = () => true;
const getServerSnapshot = () => false;

const firstParam = (value: string | string[] | undefined): string =>
  Array.isArray(value) ? value[0] ?? '' : value ?? '';

export default function InvitePage() {
  const params = useLocalSearchParams<{ kind?: string | string[]; token?: string | string[] }>();
  const { width } = useWindowDimensions();
  const hydrated = useSyncExternalStore(subscribeToHydration, getClientSnapshot, getServerSnapshot);
  const [preview, setPreview] = useState<InvitePreview>();
  const [joining, setJoining] = useState(false);
  const [error, setError] = useState('');
  const invitation = useMemo<Invitation | undefined>(() => {
    if (!hydrated) return undefined;
    const kind = firstParam(params.kind) as InviteKind;
    const token = firstParam(params.token);
    return inviteKinds.has(kind) && token ? { kind, token } : undefined;
  }, [hydrated, params.kind, params.token]);

  useEffect(() => {
    if (!invitation) return;
    let active = true;
    createApi(false)
      .invitePreview(invitation)
      .then((value) => {
        if (active) setPreview(value);
      })
      .catch((value) => {
        if (active) setError(value instanceof Error ? value.message : 'This invitation could not be opened.');
      });
    return () => {
      active = false;
    };
  }, [invitation]);

  if (joining && invitation) {
    return <AppEntry invitation={invitation} invitePreview={preview} />;
  }

  const deepLink = invitation
    ? `frogbot://invite?kind=${invitation.kind}&token=${encodeURIComponent(invitation.token)}`
    : 'frogbot://';
  const visibleError = hydrated ? (invitation ? error : 'This invitation link is incomplete.') : '';
  const label = preview?.kind === 'group' ? 'GROUP INVITE' : preview?.kind === 'skill' ? 'SHARED SKILL' : 'FROGGYBOT INVITE';
  const cardWidth = Math.min(720, Math.max(280, width - 40));

  return (
    <SafeAreaView style={styles.safeArea}>
      <Head>
        <title>You&apos;re invited to FroggyBot</title>
        <meta name="description" content="Join friends and their AI teammates in FroggyBot." />
        <meta property="og:title" content="You&apos;re invited to FroggyBot" />
        <meta property="og:description" content="Join friends and their AI teammates in one shared conversation." />
        <meta property="og:image" content="https://froggybot.com/frogbot-invite-card.png" />
        <meta property="og:image:width" content="1200" />
        <meta property="og:image:height" content="630" />
        <meta property="og:type" content="website" />
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="theme-color" content="#007A3D" />
        <meta name="apple-itunes-app" content={`app-id=6808396807, app-argument=${deepLink}`} />
      </Head>
      <ScrollView contentContainerStyle={styles.page} showsVerticalScrollIndicator={false}>
        <Link href="/" style={[styles.brand, { width: cardWidth }]}>
          <Image accessibilityIgnoresInvertColors source={frog} resizeMode="contain" style={styles.logo} />
          <Text style={styles.brandName}>FroggyBot</Text>
        </Link>

        <View style={[styles.card, { width: cardWidth }]}>
          {!preview && !visibleError ? (
            <View style={styles.loading}>
              <ActivityIndicator color="#007A3D" />
              <Text style={styles.loadingText}>Opening your invitation...</Text>
            </View>
          ) : visibleError ? (
            <View style={styles.empty}>
              <Image accessibilityIgnoresInvertColors source={frog} resizeMode="contain" style={styles.heroFrog} />
              <Text accessibilityRole="header" style={styles.title}>This invite has hopped away.</Text>
              <Text style={styles.description}>{visibleError} Ask your friend to share a fresh link.</Text>
              <Link href="/" style={styles.secondaryButton}>
                <Text style={styles.secondaryButtonText}>Visit FroggyBot</Text>
              </Link>
            </View>
          ) : preview ? (
            <>
              <View style={styles.inviteVisual}>
                <View style={styles.glowOne} />
                <View style={styles.glowTwo} />
                <View style={styles.frogCircle}>
                  <Image accessibilityIgnoresInvertColors source={frog} resizeMode="contain" style={styles.heroFrog} />
                </View>
                {preview.bots.length ? (
                  <View style={styles.botStack}>
                    {preview.bots.slice(0, 4).map((bot, index) => (
                      <View key={`${bot.name}-${index}`} style={[styles.botStackItem, { marginLeft: index ? -9 : 0, zIndex: 4 - index }]}>
                        <BotAvatar name={bot.name} color={bot.color} size={42} />
                      </View>
                    ))}
                  </View>
                ) : null}
              </View>
              <View style={styles.copy}>
                <Text style={styles.eyebrow}>{label}</Text>
                <Text accessibilityRole="header" style={styles.title}>{preview.title}</Text>
                <Text style={styles.description}>{preview.description}</Text>
                {preview.kind === 'group' ? (
                  <>
                    <View style={styles.stats}>
                      <View style={styles.stat}>
                        <Text style={styles.statNumber}>{preview.peopleCount ?? 1}</Text>
                        <Text style={styles.statLabel}>PEOPLE</Text>
                      </View>
                      <View style={styles.divider} />
                      <View style={styles.stat}>
                        <Text style={styles.statNumber}>{preview.bots.length}</Text>
                        <Text style={styles.statLabel}>FROGGYBOTS</Text>
                      </View>
                    </View>
                    <Text style={styles.easyJoin}>One email code. No password. You’ll land directly in the shared conversation.</Text>
                  </>
                ) : null}
                <Pressable
                  accessibilityRole="button"
                  style={({ pressed }) => [styles.primaryButton, pressed && styles.pressed]}
                  onPress={() => setJoining(true)}>
                  <Text style={styles.primaryButtonText}>
                    {preview.kind === 'group' ? 'Join the group' : preview.kind === 'skill' ? 'Add this skill' : 'Add to my team'}
                  </Text>
                  <Text style={styles.arrow}>→</Text>
                </Pressable>
                {Platform.OS === 'web' ? (
                  <Pressable accessibilityRole="link" onPress={() => Linking.openURL(deepLink)}>
                    <Text style={styles.openApp}>Already have the app? Open FroggyBot</Text>
                  </Pressable>
                ) : null}
                <Text style={styles.inviteOnly}>FroggyBot is invite-only. This link unlocks your account.</Text>
              </View>
            </>
          ) : null}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: '#F4F2EC' },
  page: { flexGrow: 1, paddingVertical: 22, paddingBottom: 44, alignItems: 'center' },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 9, maxWidth: 720, marginBottom: 22 },
  logo: { width: 35, height: 31, borderRadius: 10 },
  brandName: { color: '#171714', fontSize: 20, fontWeight: '800', letterSpacing: -0.5 },
  card: { maxWidth: 720, borderRadius: 30, overflow: 'hidden', backgroundColor: '#FFFFFF', borderWidth: 1, borderColor: '#DEDAD0', ...Platform.select({ web: { boxShadow: '0 24px 70px rgba(31,45,35,0.11)' }, default: { shadowColor: '#1F2D23', shadowOpacity: 0.11, shadowRadius: 32, shadowOffset: { width: 0, height: 18 } } }) },
  inviteVisual: { minHeight: 250, backgroundColor: '#007A3D', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' },
  glowOne: { position: 'absolute', width: 270, height: 270, borderRadius: 135, backgroundColor: '#1C9358', top: -130, right: -40 },
  glowTwo: { position: 'absolute', width: 220, height: 220, borderRadius: 110, backgroundColor: '#006633', bottom: -130, left: -30 },
  frogCircle: { width: 126, height: 126, borderRadius: 42, backgroundColor: '#F4F2EC', alignItems: 'center', justifyContent: 'center', borderWidth: 7, borderColor: 'rgba(255,255,255,0.25)' },
  heroFrog: { width: 98, height: 98, borderRadius: 28 },
  botStack: { position: 'absolute', bottom: 18, flexDirection: 'row', alignItems: 'center' },
  botStackItem: { borderRadius: 23, borderWidth: 3, borderColor: '#007A3D', backgroundColor: '#FFFFFF' },
  copy: { paddingHorizontal: 26, paddingTop: 30, paddingBottom: 26, alignItems: 'center' },
  eyebrow: { color: '#007A3D', fontSize: 11, fontWeight: '800', letterSpacing: 1.5, marginBottom: 10 },
  title: { color: '#171714', fontSize: 32, lineHeight: 37, fontWeight: '800', letterSpacing: -1.1, textAlign: 'center' },
  description: { alignSelf: 'stretch', color: '#6E6A62', fontSize: 16, lineHeight: 24, textAlign: 'center', maxWidth: 520, marginTop: 11 },
  stats: { flexDirection: 'row', alignItems: 'center', marginTop: 24, marginBottom: 3, paddingHorizontal: 24, paddingVertical: 13, borderRadius: 18, backgroundColor: '#F4F7F4' },
  stat: { minWidth: 88, alignItems: 'center' },
  statNumber: { color: '#173D2A', fontSize: 20, fontWeight: '800' },
  statLabel: { color: '#779181', fontSize: 9, fontWeight: '800', letterSpacing: 1.1, marginTop: 2 },
  divider: { width: 1, height: 30, backgroundColor: '#D3E0D8' },
  easyJoin: { color: '#62776B', fontSize: 12, lineHeight: 18, textAlign: 'center', maxWidth: 360, marginTop: 11 },
  primaryButton: { alignSelf: 'stretch', maxWidth: 420, height: 58, paddingHorizontal: 21, borderRadius: 18, backgroundColor: '#007A3D', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 25 },
  primaryButtonText: { color: '#FFFFFF', fontSize: 16, fontWeight: '700' },
  arrow: { color: '#FFFFFF', fontSize: 23, marginTop: -2 },
  openApp: { color: '#007A3D', fontSize: 14, fontWeight: '700', marginTop: 19 },
  inviteOnly: { alignSelf: 'stretch', color: '#99958C', fontSize: 12, textAlign: 'center', marginTop: 18 },
  loading: { minHeight: 530, alignItems: 'center', justifyContent: 'center', gap: 13 },
  loadingText: { color: '#7D7970', fontSize: 14 },
  empty: { minHeight: 530, padding: 30, alignItems: 'center', justifyContent: 'center' },
  secondaryButton: { height: 50, paddingHorizontal: 24, borderRadius: 16, backgroundColor: '#E7F2EC', justifyContent: 'center', marginTop: 25 },
  secondaryButtonText: { color: '#007A3D', fontSize: 15, fontWeight: '700' },
  pressed: { opacity: 0.76 },
});
