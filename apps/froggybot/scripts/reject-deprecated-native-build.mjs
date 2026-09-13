const platform = process.env.EAS_BUILD_PLATFORM ?? 'native';

console.error(
  `FroggyBot's Expo ${platform} build is deprecated and intentionally disabled.\n` +
    'Build iPhone and Mac releases from apps/froggybot-apple instead:\n' +
    '  ./scripts/apple-app.sh build ios\n' +
    '  APPLE_TEAM_ID=TEAMID ./scripts/apple-app.sh testflight ios',
);
process.exit(1);
