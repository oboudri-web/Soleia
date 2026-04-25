/**
 * Soleia - Onboarding flag + Push-prompt tracking via AsyncStorage.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

const ONBOARDING_KEY = '@soleia/onboarding_done_v1';
const PUSH_PROMPTED_KEY = '@soleia/push_prompted_v1';
const PUSH_TOKEN_KEY = '@soleia/push_token_v1';

export async function isOnboardingDone(): Promise<boolean> {
  try {
    const v = await AsyncStorage.getItem(ONBOARDING_KEY);
    return v === 'true';
  } catch {
    return false;
  }
}

export async function setOnboardingDone(): Promise<void> {
  try {
    await AsyncStorage.setItem(ONBOARDING_KEY, 'true');
  } catch {}
}

export async function resetOnboarding(): Promise<void> {
  try {
    await AsyncStorage.removeItem(ONBOARDING_KEY);
  } catch {}
}

export async function isPushPrompted(): Promise<boolean> {
  try {
    const v = await AsyncStorage.getItem(PUSH_PROMPTED_KEY);
    return v === 'true';
  } catch {
    return false;
  }
}

export async function setPushPrompted(): Promise<void> {
  try {
    await AsyncStorage.setItem(PUSH_PROMPTED_KEY, 'true');
  } catch {}
}

export async function setStoredPushToken(token: string): Promise<void> {
  try {
    await AsyncStorage.setItem(PUSH_TOKEN_KEY, token);
  } catch {}
}

export async function getStoredPushToken(): Promise<string | null> {
  try {
    return (await AsyncStorage.getItem(PUSH_TOKEN_KEY)) || null;
  } catch {
    return null;
  }
}


// Map theme preference : 'auto' (suit système) | 'light' | 'dark'
const MAP_THEME_KEY = '@soleia/map_theme_v1';

export type MapThemePref = 'auto' | 'light' | 'dark';

export async function getMapThemePref(): Promise<MapThemePref> {
  try {
    const v = await AsyncStorage.getItem(MAP_THEME_KEY);
    if (v === 'light' || v === 'dark' || v === 'auto') return v;
    return 'auto';
  } catch {
    return 'auto';
  }
}

export async function setMapThemePref(pref: MapThemePref): Promise<void> {
  try {
    await AsyncStorage.setItem(MAP_THEME_KEY, pref);
  } catch {}
}
