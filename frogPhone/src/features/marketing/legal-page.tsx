import { Link } from 'expo-router';
import Head from 'expo-router/head';
import { Image, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

const frog = require('../../../assets/images/frogbot-foreground.png');

type Section = {
  title: string;
  paragraphs: string[];
};

type Props = {
  title: string;
  description: string;
  sections: Section[];
};

export function LegalPage({ title, description, sections }: Props) {
  return (
    <>
      <Head>
        <title>{title} — FrogBot</title>
        <meta name="description" content={description} />
        <meta name="theme-color" content="#F4F2EC" />
      </Head>
      <ScrollView style={styles.scroll} contentContainerStyle={styles.page}>
        <View style={styles.header}>
          <Link href="/" asChild>
            <Pressable accessibilityRole="link" style={styles.wordmark}>
              <Image accessibilityIgnoresInvertColors source={frog} resizeMode="contain" style={styles.logo} />
              <Text style={styles.brandName}>FrogBot</Text>
            </Pressable>
          </Link>
          <Link href="/app" style={styles.loginLink}>
            Log in
          </Link>
        </View>
        <View style={styles.content}>
          <Text style={styles.eyebrow}>FROGBOT</Text>
          <Text accessibilityRole="header" style={styles.title}>
            {title}
          </Text>
          <Text style={styles.updated}>Effective September 3, 2026</Text>
          <Text style={styles.intro}>{description}</Text>
          {sections.map((section) => (
            <View key={section.title} style={styles.section}>
              <Text accessibilityRole="header" style={styles.sectionTitle}>
                {section.title}
              </Text>
              {section.paragraphs.map((paragraph) => (
                <Text key={paragraph} style={styles.body}>
                  {paragraph}
                </Text>
              ))}
            </View>
          ))}
        </View>
        <View style={styles.footer}>
          <Text style={styles.footerText}>© 2026 FrogBot</Text>
          <View style={styles.footerLinks}>
            <Link href="/privacy" style={styles.footerLink}>
              Privacy
            </Link>
            <Link href="/terms" style={styles.footerLink}>
              Terms
            </Link>
          </View>
        </View>
      </ScrollView>
    </>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1, backgroundColor: '#F4F2EC' },
  page: { minHeight: '100%', backgroundColor: '#F4F2EC' },
  header: { width: '100%', maxWidth: 980, alignSelf: 'center', paddingHorizontal: 24, paddingVertical: 22, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  wordmark: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  logo: { width: 34, height: 29 },
  brandName: { color: '#13130F', fontSize: 20, fontWeight: '800', letterSpacing: -0.5 },
  loginLink: { color: '#007A3D', fontSize: 14, fontWeight: '700' },
  content: { width: '100%', maxWidth: 760, alignSelf: 'center', paddingHorizontal: 24, paddingTop: 72, paddingBottom: 90 },
  eyebrow: { color: '#007A3D', fontSize: 11, fontWeight: '800', letterSpacing: 1.4 },
  title: { color: '#171713', fontSize: 48, lineHeight: 54, fontWeight: '800', letterSpacing: -1.9, marginTop: 15 },
  updated: { color: '#8A867D', fontSize: 13, marginTop: 16 },
  intro: { color: '#5F5B53', fontSize: 18, lineHeight: 29, marginTop: 30 },
  section: { borderTopWidth: 1, borderColor: '#D1CDC3', paddingTop: 25, marginTop: 36 },
  sectionTitle: { color: '#24231E', fontSize: 21, fontWeight: '700', letterSpacing: -0.35 },
  body: { color: '#625E56', fontSize: 15, lineHeight: 25, marginTop: 13 },
  footer: { width: '100%', maxWidth: 980, alignSelf: 'center', borderTopWidth: 1, borderColor: '#D1CDC3', paddingHorizontal: 24, paddingVertical: 28, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  footerText: { color: '#8A867D', fontSize: 12 },
  footerLinks: { flexDirection: 'row', gap: 20 },
  footerLink: { color: '#5F5B53', fontSize: 12, fontWeight: '600' },
});
