import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

const REPLY_CHANNEL_ID = 'agent-replies';

if (Platform.OS !== 'web') {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldPlaySound: true,
      shouldSetBadge: false,
      shouldShowBanner: true,
      shouldShowList: true,
    }),
  });
}

export async function registerForReplyNotifications(): Promise<string | null> {
  if (Platform.OS === 'web' || !Device.isDevice) return null;

  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync(REPLY_CHANNEL_ID, {
      name: 'Agent replies',
      importance: Notifications.AndroidImportance.HIGH,
      sound: 'default',
      vibrationPattern: [0, 180],
      lightColor: '#007A3D',
    });
  }

  let permissions = await Notifications.getPermissionsAsync();
  if (!permissions.granted) permissions = await Notifications.requestPermissionsAsync();
  if (!permissions.granted) return null;

  const projectId = Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
  if (!projectId) throw new Error('Push notification project ID is unavailable.');
  return (await Notifications.getExpoPushTokenAsync({ projectId })).data;
}

function botIdFromResponse(response: Notifications.NotificationResponse | null): string | null {
  const botId = response?.notification.request.content.data?.botId;
  return typeof botId === 'string' && botId ? botId : null;
}

export async function consumeInitialNotificationBotId(): Promise<string | null> {
  if (Platform.OS === 'web') return null;
  const response = await Notifications.getLastNotificationResponseAsync();
  const botId = botIdFromResponse(response);
  if (botId) await Notifications.clearLastNotificationResponseAsync();
  return botId;
}

export function subscribeToNotificationReplies(onBotSelected: (botId: string) => void) {
  if (Platform.OS === 'web') return { remove: () => undefined };
  return Notifications.addNotificationResponseReceivedListener((response) => {
    const botId = botIdFromResponse(response);
    if (botId) onBotSelected(botId);
  });
}
