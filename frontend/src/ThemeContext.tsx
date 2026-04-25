/**
 * SunTerrace - Theme Context
 */
import React, { createContext, useContext } from 'react';
import { useColorScheme } from 'react-native';
import { COLORS } from './theme';

type Theme = typeof COLORS.light;

const ThemeContext = createContext<{ theme: Theme; isDark: boolean }>({
  theme: COLORS.light,
  isDark: false,
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const scheme = useColorScheme();
  const isDark = scheme === 'dark';
  const theme = isDark ? COLORS.dark : COLORS.light;
  return (
    <ThemeContext.Provider value={{ theme, isDark }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
