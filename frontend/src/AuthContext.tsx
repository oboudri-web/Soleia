/**
 * Soleia - Simplified auth context (local favorites only).
 *
 * Google Sign-In has been removed to simplify the EAS build. Favorites are
 * stored in AsyncStorage and stay on-device. The `useAuth()` / `useFavorites()`
 * hooks keep the same public shape so existing call sites don't break.
 */
import React, { createContext, useContext, useEffect, useCallback, useMemo, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

const LOCAL_FAV_KEY = 'soleia_favorites_v1';
const LEGACY_FAV_KEY = '@soleia/favorites_v1'; // migrated once to LOCAL_FAV_KEY

// Minimal user type — always null in local-only mode, kept for API compat.
export type LocalUser = null;

export type AuthState = {
  ready: boolean;
  user: LocalUser;
  sessionToken: null;
  favoriteIds: string[];
  loading: boolean;
  nativeAvailable: false;
};

type AuthContextValue = AuthState & {
  login: () => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  toggleFavorite: (terraceId: string) => Promise<void>;
  setFavorites: (ids: string[]) => Promise<void>;
  isFavorite: (terraceId: string) => boolean;
};

const AuthContext = createContext<AuthContextValue | null>(null);

async function readLocalFavorites(): Promise<string[]> {
  try {
    const raw = await AsyncStorage.getItem(LOCAL_FAV_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed.filter((x) => typeof x === 'string');
    }
    // One-shot migration from legacy key
    const legacy = await AsyncStorage.getItem(LEGACY_FAV_KEY);
    if (legacy) {
      const parsed = JSON.parse(legacy);
      if (Array.isArray(parsed)) {
        const ids = parsed.filter((x) => typeof x === 'string');
        if (ids.length) {
          await AsyncStorage.setItem(LOCAL_FAV_KEY, JSON.stringify(ids));
          await AsyncStorage.removeItem(LEGACY_FAV_KEY);
        }
        return ids;
      }
    }
    return [];
  } catch {
    return [];
  }
}

async function writeLocalFavorites(ids: string[]) {
  try {
    await AsyncStorage.setItem(LOCAL_FAV_KEY, JSON.stringify(ids));
  } catch {
    // ignore
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [favoriteIds, setFavoriteIdsState] = useState<string[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const ids = await readLocalFavorites();
      if (cancelled) return;
      setFavoriteIdsState(ids);
      setReady(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // No-op login/logout — kept for API compat so callers don't crash.
  const login = useCallback(async () => {
    // Google Sign-In disabled — favorites stay local-only.
  }, []);

  const logout = useCallback(async () => {
    // Nothing to do: there's no session to clear.
  }, []);

  const refreshUser = useCallback(async () => {
    // No-op in local-only mode.
  }, []);

  const setFavorites = useCallback(async (ids: string[]) => {
    const deduped = Array.from(new Set(ids.filter(Boolean))).slice(0, 500);
    setFavoriteIdsState(deduped);
    await writeLocalFavorites(deduped);
  }, []);

  const toggleFavorite = useCallback(async (terraceId: string) => {
    if (!terraceId) return;
    const next = favoriteIds.includes(terraceId)
      ? favoriteIds.filter((x) => x !== terraceId)
      : [terraceId, ...favoriteIds];
    await setFavorites(next);
  }, [favoriteIds, setFavorites]);

  const isFavorite = useCallback(
    (terraceId: string) => favoriteIds.includes(terraceId),
    [favoriteIds],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      ready,
      user: null,
      sessionToken: null,
      favoriteIds,
      loading: false,
      nativeAvailable: false as const,
      login,
      logout,
      refreshUser,
      toggleFavorite,
      setFavorites,
      isFavorite,
    }),
    [ready, favoriteIds, login, logout, refreshUser, toggleFavorite, setFavorites, isFavorite],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return ctx;
}

/** Convenience hook — just the favorites slice. */
export function useFavorites() {
  const { favoriteIds, toggleFavorite, setFavorites, isFavorite } = useAuth();
  return { favoriteIds, toggleFavorite, setFavorites, isFavorite, synced: false };
}
