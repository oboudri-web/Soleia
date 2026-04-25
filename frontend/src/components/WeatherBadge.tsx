/**
 * Weather Badge component
 */
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../ThemeContext';
import { SPACING, RADIUS, FONT_SIZES } from '../theme';
import type { Weather } from '../api';

export default function WeatherBadge({ weather }: { weather: Weather | null }) {
  const { theme } = useTheme();
  if (!weather) return null;

  const weatherIcon = (code: number, isDay: boolean): any => {
    if (code === 0) return isDay ? 'sunny' : 'moon';
    if (code <= 3) return isDay ? 'partly-sunny' : 'cloudy-night';
    if (code >= 45 && code <= 48) return 'cloud';
    if (code >= 51 && code <= 65) return 'rainy';
    if (code >= 71 && code <= 77) return 'snow';
    if (code >= 80 && code <= 82) return 'rainy';
    if (code >= 95) return 'thunderstorm';
    return 'cloud';
  };

  return (
    <View
      style={[
        styles.container,
        { backgroundColor: theme.surface, borderColor: theme.border },
      ]}
      testID="weather-badge"
    >
      <Ionicons
        name={weatherIcon(weather.weather_code, weather.is_day)}
        size={20}
        color={theme.primary}
      />
      <View>
        <Text style={[styles.temp, { color: theme.text }]}>
          {Math.round(weather.temperature)}°
        </Text>
        <Text style={[styles.label, { color: theme.textSecondary }]} numberOfLines={1}>
          {weather.weather_label}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.sm,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.08,
    shadowRadius: 12,
    elevation: 4,
    minWidth: 120,
  },
  temp: {
    fontSize: FONT_SIZES.h4,
    fontWeight: '700',
    lineHeight: 20,
  },
  label: {
    fontSize: 10,
    fontWeight: '500',
    maxWidth: 80,
  },
});
