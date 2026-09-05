import { Link } from 'expo-router';
import Head from 'expo-router/head';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Image, Linking, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { loadPublicCatalog } from '@/lib/public-catalog';
import type { Capability, PublicCatalog, Skill } from '@/lib/types';

import { CatalogCard } from './catalog-card';
import { useNarrowLayout } from './use-narrow-layout';

const frog = require('../../../assets/images/frogbot-foreground.png');
const defaultRepository = 'https://github.com/tmoreton/frogbot-capabilities';

type CatalogTab = 'skills' | 'tools';

const searchableText = (item: Capability) =>
  [item.name, item.description, item.category, item.author, ...(item.tags ?? []), ...(item.actions ?? [])]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();

export function PublicCatalogPage() {
  const narrow = useNarrowLayout();
  const [catalog, setCatalog] = useState<PublicCatalog>();
  const [tab, setTab] = useState<CatalogTab>('skills');
  const [category, setCategory] = useState('All');
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    loadPublicCatalog()
      .then((value) => {
        if (active) setCatalog(value);
      })
      .catch((value: unknown) => {
        if (active) setError(value instanceof Error ? value.message : 'The directory could not be loaded.');
      });
    return () => {
      active = false;
    };
  }, []);

  const items: (Skill | Capability)[] = tab === 'skills' ? catalog?.skills ?? [] : catalog?.tools ?? [];
  const categories = ['All', ...Array.from(new Set(items.map((item) => item.category ?? 'General'))).sort()];
  const normalizedQuery = query.trim().toLowerCase();
  const visible = items
    .filter((item) => category === 'All' || (item.category ?? 'General') === category)
    .filter((item) => !normalizedQuery || searchableText(item).includes(normalizedQuery))
    .sort((left, right) => Number(Boolean(right.featured)) - Number(Boolean(left.featured)) || left.name.localeCompare(right.name));
  const repository = catalog?.repositoryUrl ?? defaultRepository;
  const contribution = catalog?.contributionUrl ?? `${defaultRepository}/blob/main/CONTRIBUTING.md`;

  const changeTab = (value: CatalogTab) => {
    setTab(value);
    setCategory('All');
    setQuery('');
  };

  return (
    <>
      <Head>
        <title>Skills & tools for FroggyBot</title>
        <meta name="description" content="Browse reviewed skills, tools, and actions for FroggyBot, then add them to a bot or contribute your own." />
        <meta property="og:title" content="FroggyBot skills & tools" />
        <meta property="og:description" content="A public library of reusable AI playbooks and reviewed actions." />
      </Head>
      <ScrollView style={styles.scroll} contentContainerStyle={styles.page}>
        <View style={[styles.header, narrow && styles.headerNarrow]}>
          <Link href="/" asChild>
            <Pressable accessibilityRole="link" style={styles.wordmark}>
              <Image accessibilityIgnoresInvertColors source={frog} resizeMode="contain" style={styles.logo} />
              {!narrow ? <Text style={styles.brand}>FroggyBot</Text> : null}
            </Pressable>
          </Link>
          <View style={styles.headerLinks}>
            <Pressable accessibilityRole="link" onPress={() => void Linking.openURL(repository)}>
              <Text style={styles.headerLink}>Contribute</Text>
            </Pressable>
            <Link href="/app" asChild>
              <Pressable accessibilityRole="link" style={styles.loginButton}>
                <Text style={styles.loginText}>Member login</Text>
              </Pressable>
            </Link>
          </View>
        </View>

        <View style={[styles.hero, narrow && styles.heroNarrow]}>
          <Text style={styles.eyebrow}>PUBLIC CAPABILITY LIBRARY</Text>
          <Text accessibilityRole="header" style={[styles.title, narrow && styles.titleNarrow]}>Give your FroggyBots better ways to help.</Text>
          <Text style={[styles.subtitle, narrow && styles.subtitleNarrow]}>
            Skills teach a repeatable way of working. Tools give bots reviewed actions. Browse everything publicly, then add what you want to a FroggyBot.
          </Text>
          <View style={styles.trustRow}>
            <Text style={styles.trustItem}>✓ Version-pinned skills</Text>
            <Text style={styles.trustItem}>✓ Reviewed tool access</Text>
            <Text style={styles.trustItem}>✓ Open contributions</Text>
          </View>
        </View>

        <View style={[styles.directory, narrow && styles.directoryNarrow]}>
          <View accessibilityRole="tablist" style={styles.tabs}>
            {(['skills', 'tools'] as const).map((value) => (
              <Pressable
                key={value}
                accessibilityRole="tab"
                accessibilityState={{ selected: tab === value }}
                style={[styles.tab, tab === value && styles.tabActive]}
                onPress={() => changeTab(value)}>
                <Text style={[styles.tabText, tab === value && styles.tabTextActive]}>
                  {value === 'skills' ? `Skills · ${catalog?.skills.length ?? '—'}` : `Tools & actions · ${catalog?.tools.length ?? '—'}`}
                </Text>
              </Pressable>
            ))}
          </View>
          <TextInput
            accessibilityLabel="Search the capability library"
            style={styles.search}
            value={query}
            onChangeText={setQuery}
            placeholder={`Search ${tab === 'skills' ? 'skills' : 'tools and actions'}`}
            placeholderTextColor="#969187"
          />
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.categories}>
            {categories.map((value) => (
              <Pressable
                key={value}
                accessibilityRole="button"
                accessibilityState={{ selected: category === value }}
                style={[styles.categoryButton, category === value && styles.categoryButtonActive]}
                onPress={() => setCategory(value)}>
                <Text style={[styles.categoryText, category === value && styles.categoryTextActive]}>{value}</Text>
              </Pressable>
            ))}
          </ScrollView>

          {!catalog && !error ? <ActivityIndicator color="#007A3D" style={styles.loader} /> : null}
          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
          {catalog && !visible.length ? <Text style={styles.empty}>No matches yet. Try another search or category.</Text> : null}
          <View style={styles.grid}>
            {visible.map((item) => <CatalogCard key={item.id} item={item} kind={tab === 'skills' ? 'skill' : 'tool'} />)}
          </View>
        </View>

        <View style={[styles.contribute, narrow && styles.contributeNarrow]}>
          <View style={styles.contributeCopy}>
            <Text style={styles.contributeEyebrow}>BUILT IN THE OPEN</Text>
            <Text accessibilityRole="header" style={styles.contributeTitle}>Know a better way to work?</Text>
            <Text style={styles.contributeText}>
              Contribute an instruction-only skill through GitHub, or propose a narrowly scoped tool. Every submission is validated and reviewed before it reaches the library.
            </Text>
          </View>
          <View style={styles.contributeActions}>
            <Pressable accessibilityRole="link" style={styles.contributeButton} onPress={() => void Linking.openURL(contribution)}>
              <Text style={styles.contributeButtonText}>Contribution guide</Text>
            </Pressable>
            <Pressable accessibilityRole="link" style={styles.repositoryButton} onPress={() => void Linking.openURL(repository)}>
              <Text style={styles.repositoryButtonText}>View public repository</Text>
            </Pressable>
          </View>
        </View>

        <View style={styles.footer}>
          <Text style={styles.footerText}>© 2026 FroggyBot</Text>
          <View style={styles.footerLinks}>
            <Link href="/" style={styles.footerLink}>Home</Link>
            <Link href="/privacy" style={styles.footerLink}>Privacy</Link>
            <Link href="/terms" style={styles.footerLink}>Terms</Link>
          </View>
        </View>
      </ScrollView>
    </>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1, backgroundColor: '#F4F2EC' },
  page: { width: '100%', minHeight: '100%', backgroundColor: '#F4F2EC' },
  header: { width: '100%', maxWidth: 1240, alignSelf: 'center', paddingHorizontal: 24, paddingVertical: 24, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  headerNarrow: { paddingHorizontal: 20, paddingVertical: 20 },
  wordmark: { flexDirection: 'row', alignItems: 'center', gap: 9 },
  logo: { width: 36, height: 31 },
  brand: { color: '#13130F', fontSize: 21, fontWeight: '800', letterSpacing: -0.55 },
  headerLinks: { flexDirection: 'row', alignItems: 'center', gap: 18 },
  headerLink: { color: '#5E5A52', fontSize: 13, fontWeight: '700' },
  loginButton: { minHeight: 42, paddingHorizontal: 18, borderRadius: 22, borderWidth: 1, borderColor: '#CECBC2', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.55)' },
  loginText: { color: '#22211D', fontSize: 13, fontWeight: '800' },
  hero: { width: '100%', maxWidth: 920, alignSelf: 'center', alignItems: 'center', paddingHorizontal: 24, paddingTop: 72, paddingBottom: 62 },
  heroNarrow: { alignItems: 'flex-start', paddingHorizontal: 20, paddingTop: 46, paddingBottom: 42 },
  eyebrow: { color: '#007A3D', fontSize: 11, fontWeight: '900', letterSpacing: 1.5 },
  title: { maxWidth: 780, color: '#13130F', fontSize: 52, lineHeight: 56, fontWeight: '800', letterSpacing: -2.3, textAlign: 'center', marginTop: 17 },
  titleNarrow: { fontSize: 39, lineHeight: 43, letterSpacing: -1.5, textAlign: 'left' },
  subtitle: { maxWidth: 730, color: '#666159', fontSize: 18, lineHeight: 28, textAlign: 'center', marginTop: 20 },
  subtitleNarrow: { fontSize: 16, lineHeight: 25, textAlign: 'left' },
  trustRow: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: 9, marginTop: 26 },
  trustItem: { color: '#416451', backgroundColor: '#E8F2EC', borderRadius: 14, overflow: 'hidden', paddingHorizontal: 12, paddingVertical: 8, fontSize: 11, fontWeight: '700' },
  directory: { width: '100%', maxWidth: 1240, alignSelf: 'center', paddingHorizontal: 24, paddingBottom: 84 },
  directoryNarrow: { paddingHorizontal: 20, paddingBottom: 60 },
  tabs: { alignSelf: 'center', minWidth: 390, flexDirection: 'row', padding: 4, borderRadius: 16, backgroundColor: '#E5E2DA' },
  tab: { flex: 1, minHeight: 44, paddingHorizontal: 16, borderRadius: 13, alignItems: 'center', justifyContent: 'center' },
  tabActive: { backgroundColor: '#FFFFFF' },
  tabText: { color: '#777168', fontSize: 13, fontWeight: '800' },
  tabTextActive: { color: '#007A3D' },
  search: { width: '100%', maxWidth: 680, alignSelf: 'center', minHeight: 54, marginTop: 26, paddingHorizontal: 19, borderRadius: 18, borderWidth: 1, borderColor: '#D8D4CA', backgroundColor: '#FFFFFF', color: '#24231F', fontSize: 15 },
  categories: { gap: 8, paddingVertical: 20, paddingHorizontal: 2, marginHorizontal: 'auto' },
  categoryButton: { minHeight: 36, paddingHorizontal: 14, borderRadius: 18, borderWidth: 1, borderColor: '#D8D4CA', alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.45)' },
  categoryButtonActive: { borderColor: '#007A3D', backgroundColor: '#E5F1EA' },
  categoryText: { color: '#6D685F', fontSize: 12, fontWeight: '700' },
  categoryTextActive: { color: '#007A3D' },
  loader: { marginVertical: 70 },
  error: { maxWidth: 620, alignSelf: 'center', color: '#9E342A', backgroundColor: '#FCECE8', padding: 15, borderRadius: 14, textAlign: 'center' },
  empty: { color: '#817C73', textAlign: 'center', marginVertical: 60 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'stretch', justifyContent: 'center', gap: 16 },
  contribute: { width: '100%', maxWidth: 1192, alignSelf: 'center', marginBottom: 82, padding: 38, borderRadius: 28, backgroundColor: '#173E2A', flexDirection: 'row', alignItems: 'center', gap: 40 },
  contributeNarrow: { width: 'auto', marginHorizontal: 20, marginBottom: 58, padding: 25, flexDirection: 'column', alignItems: 'stretch', gap: 24 },
  contributeCopy: { flex: 1 },
  contributeEyebrow: { color: '#88C8A5', fontSize: 10, fontWeight: '900', letterSpacing: 1.3 },
  contributeTitle: { color: '#FFFFFF', fontSize: 29, fontWeight: '800', letterSpacing: -0.8, marginTop: 9 },
  contributeText: { maxWidth: 680, color: '#C9DCCE', fontSize: 14, lineHeight: 22, marginTop: 10 },
  contributeActions: { minWidth: 210, gap: 10 },
  contributeButton: { minHeight: 46, paddingHorizontal: 17, borderRadius: 14, backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center' },
  contributeButtonText: { color: '#173E2A', fontSize: 13, fontWeight: '800' },
  repositoryButton: { minHeight: 44, paddingHorizontal: 17, borderRadius: 14, borderWidth: 1, borderColor: '#52765F', alignItems: 'center', justifyContent: 'center' },
  repositoryButtonText: { color: '#E1EEE5', fontSize: 12, fontWeight: '700' },
  footer: { width: '100%', maxWidth: 1240, alignSelf: 'center', paddingHorizontal: 24, paddingVertical: 30, borderTopWidth: 1, borderColor: '#D8D4CA', flexDirection: 'row', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 },
  footerText: { color: '#8B867D', fontSize: 11 },
  footerLinks: { flexDirection: 'row', gap: 20 },
  footerLink: { color: '#6E6960', fontSize: 11 },
});
