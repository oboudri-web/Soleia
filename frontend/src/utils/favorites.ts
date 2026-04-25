/**
 * Soleia - Favorites helper (AsyncStorage-based, MVP no auth).
 * List of terrace IDs saved by the user; used for push notifications + Profile.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

const KEY = '@soleia/favorites_v1';

export async function getFavorites(): Promise<string[]> {
  try {
    const raw = await AsyncStorage.getItem(KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr.filter((x) => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

export async function isFavorite(id: string): Promise<boolean> {
  const list = await getFavorites();
  return list.includes(id);
}

export async function addFavorite(id: string): Promise<string[]> {
  const list = await getFavorites();
  if (list.includes(id)) return list;
  const next = [id, ...list].slice(0, 500);
  await AsyncStorage.setItem(KEY, JSON.stringify(next));
  return next;
}

export async function removeFavorite(id: string): Promise<string[]> {
  const list = await getFavorites();
  const next = list.filter((x) => x !== id);
  await AsyncStorage.setItem(KEY, JSON.stringify(next));
  return next;
}

export async function toggleFavorite(id: string): Promise<{ favorited: boolean; list: string[] }> {
  const current = await isFavorite(id);
  const list = current ? await removeFavorite(id) : await addFavorite(id);
  return { favorited: !current, list };
}
