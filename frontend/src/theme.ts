/**
 * SunTerrace - Theme & Constants
 */
export const COLORS = {
  light: {
    primary: '#F5A623',
    primaryDark: '#D98E0F',
    background: '#FFFFFF',
    surface: '#FFFFFF',
    surfaceSecondary: '#F7F5F0',
    surfaceTertiary: '#EFECE3',
    text: '#000000',
    textSecondary: '#666666',
    textTertiary: '#999999',
    border: '#EAEAEA',
    markerSunny: '#F5A623',
    markerSoon: '#FF8C00',
    markerShade: '#BDBDBD',
    overlay: 'rgba(0,0,0,0.5)',
    success: '#34C759',
    shadow: '#000000',
  },
  dark: {
    primary: '#F5A623',
    primaryDark: '#D98E0F',
    background: '#000000',
    surface: '#1C1C1E',
    surfaceSecondary: '#2C2C2E',
    surfaceTertiary: '#3A3A3C',
    text: '#FFFFFF',
    textSecondary: '#A0A0A0',
    textTertiary: '#6E6E70',
    border: '#333333',
    markerSunny: '#F5A623',
    markerSoon: '#FF8C00',
    markerShade: '#666666',
    overlay: 'rgba(0,0,0,0.7)',
    success: '#30D158',
    shadow: '#000000',
  },
};

export const SPACING = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
};

export const FONT_SIZES = {
  h1: 34,
  h2: 28,
  h3: 22,
  h4: 18,
  body: 16,
  small: 14,
  caption: 12,
};

export const RADIUS = {
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
  pill: 999,
};

export const TYPE_LABELS: Record<string, string> = {
  bar: 'Bar',
  cafe: 'Café',
  restaurant: 'Restaurant',
  rooftop: 'Rooftop',
};

export const TYPE_ICONS: Record<string, string> = {
  bar: 'wine',
  cafe: 'cafe',
  restaurant: 'restaurant',
  rooftop: 'business',
};

export const SUN_STATUS_LABELS: Record<string, string> = {
  sunny: 'Au soleil',
  soon: 'Soleil bientôt',
  shade: 'À l\'ombre',
};
