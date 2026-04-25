/**
 * Soleia - Push notifications registration helper.
 * Uses expo-notifications + registers the token with our backend.
 */
import { Platform } from 'react-native';
import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import { api } from '../api';
import { isPushPrompted, setPushPrompted, setStoredPushToken, getStoredPushToken } from './appState';

/**
 * Requests push permission, fetches an Expo push token, and registers with backend.
 * Returns the token (or null if denied / unsupported).
 *
 * Guarded by AsyncStorage: once the user has been prompted (accepted or denied),
 * we won't prompt again automatically.
 */
export async function requestPushPermissionAndRegister(city?: string): Promise<string | null> {
  if (Platform.OS === 'web') return null;
  if (!Device.isDevice) return null; // Skip in simulators

  if (await isPushPrompted()) {
    // Already prompted once — refresh token silently if we already had permission.
    const existing = await getStoredPushToken();
    if (existing) return existing;
    try {
      const { status } = await Notifications.getPermissionsAsync();
      if (status !== 'granted') return null;
    } catch {
      return null;
    }
  }

  try {
    // Configure default channel on Android.
    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('default', {
        name: 'default',
        importance: Notifications.AndroidImportance.DEFAULT,
        lightColor: '#F5A623',
      });
    }

    const existing = await Notifications.getPermissionsAsync();
    let status = existing.status;
    if (status !== 'granted') {
      const req = await Notifications.requestPermissionsAsync();
      status = req.status;
    }
    await setPushPrompted();
    if (status !== 'granted') return null;

    const tokenResp = await Notifications.getExpoPushTokenAsync();
    const token = tokenResp.data;
    if (!token) return null;
    await setStoredPushToken(token);

    try {
      await api.registerPushToken(token, city);
    } catch (e) {
      // Keep the token locally even if backend register failed.
      console.warn('[push] backend register failed', e);
    }
    return token;
  } catch (e) {
    console.warn('[push] request failed', e);
    return null;
  }
}
