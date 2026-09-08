export const CHIEF_COLOR = '#007A3D';
export const CHIEF_TEMPLATE_ID = 'chief';
const DEFAULT_BOT_COLOR = '#58BEAA';
export const BOT_COLORS = [DEFAULT_BOT_COLOR, '#FFAA34', '#6C5CE7', '#3984F6', '#F46A27', '#E95383'];

type BrandedBot = { color: string; systemRole?: 'chief' };

export const displayBotColor = (bot: BrandedBot) =>
  bot.systemRole === 'chief'
    ? CHIEF_COLOR
    : bot.color === CHIEF_COLOR
      ? DEFAULT_BOT_COLOR
      : bot.color;

export const chiefFirst = <BotType extends Pick<BrandedBot, 'systemRole'>>(bots: BotType[]) =>
  [...bots].sort(
    (left, right) => Number(right.systemRole === 'chief') - Number(left.systemRole === 'chief'),
  );
