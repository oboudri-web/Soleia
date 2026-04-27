/**
 * Soleia - TerraceCard minimaliste (photo 72x72 + infos compactes)
 */
import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Image } from 'react-native';
import { useTheme } from '../ThemeContext';
import { SPACING, FONT_SIZES, TYPE_LABELS } from '../theme';
import { hhmmToFr } from '../utils/time';
import { isOpenAt } from '../utils/openingHours';
import type { Terrace } from '../api';

type Props = {
  terrace: Terrace;
  onPress: () => void;
};

export default function TerraceCard({ terrace, onPress }: Props) {
  const { theme } = useTheme();

  // Closed-state detection (takes priority over sun status)
  const openState = isOpenAt((terrace as any).opening_hours, new Date());
  const isClosed = openState === false;

  const statusColor = isClosed
    ? '#9E9E9E'
    : terrace.sun_status === 'sunny'
    ? '#F5A623'
    : '#888888';
  const statusLabel = isClosed
    ? 'Fermé'
    : terrace.sun_status === 'sunny'
    ? 'Au soleil'
    : terrace.sun_status === 'soon'
    ? 'Bientôt'
    : "À l'ombre";

  const sunLine = isClosed
    ? null
    : terrace.sun_status === 'sunny' && terrace.sunny_until
    ? `\u2600\uFE0F Au soleil jusqu'\u00e0 ${hhmmToFr(terrace.sunny_until)}`
    : terrace.sun_status === 'soon' && terrace.next_sunny_time
    ? `\u2600\uFE0F Au soleil \u00e0 ${hhmmToFr(terrace.next_sunny_time)}`
    : terrace.sun_status === 'shade' && terrace.next_sunny_time
    ? `\u2600\uFE0F Au soleil \u00e0 ${hhmmToFr(terrace.next_sunny_time)}`
    : null;

  // Sun stat: % of 6h-22h window where the terrace is sunny + total duration in hours.
  // Uses pre-computed `shadow_sunny_minutes` from /api/terraces (within 6h-22h = 960 min).
  const SUN_WINDOW_MIN = 16 * 60; // 6h → 22h
  const sunMin = terrace.shadow_sunny_minutes;
  const sunStat = (sunMin != null && sunMin > 0)
    ? {
        pct: Math.min(100, Math.round((sunMin / SUN_WINDOW_MIN) * 100)),
        hours: Math.round((sunMin / 60) * 10) / 10, // 1 décimale
      }
    : null;

  return (
    <TouchableOpacity
      activeOpacity={0.7}
      onPress={onPress}
      testID={`terrace-card-${terrace.id}`}
      style={[styles.card, { backgroundColor: theme.surface }]}
    >
      <View style={styles.photoWrap}>
        <Image source={{ uri: terrace.photo_url }} style={styles.image} />
        <View style={[styles.badge, { backgroundColor: statusColor }]}>
          <Text style={styles.badgeText} numberOfLines={1}>
            {statusLabel}
          </Text>
        </View>
      </View>

      <View style={styles.content}>
        <View style={styles.topRow}>
          <Text
            style={[styles.name, { color: theme.text }]}
            numberOfLines={1}
          >
            {terrace.name}
          </Text>
          {typeof terrace.google_rating === 'number' ? (
            <Text style={[styles.rating, { color: '#F5A623' }]}>
              {String.fromCodePoint(0x2B50)} {terrace.google_rating.toFixed(1)}
              {terrace.google_ratings_count && terrace.google_ratings_count > 0 ? (
                <Text style={styles.ratingCount}> ({terrace.google_ratings_count})</Text>
              ) : null}
            </Text>
          ) : null}
        </View>

        <Text style={[styles.subtitle, { color: theme.textSecondary }]}>
          {TYPE_LABELS[terrace.type] || terrace.type} · {terrace.orientation_label}
          {terrace.distance_km !== null && terrace.distance_km !== undefined
            ? ` · ${terrace.distance_km.toFixed(1)} km`
            : ''}
        </Text>

        {terrace.ai_description && (
          <Text
            style={[styles.description, { color: theme.textSecondary }]}
            numberOfLines={2}
          >
            {terrace.ai_description}
          </Text>
        )}

        {sunStat && (
          <View style={styles.sunStatRow}>
            <Text style={styles.sunStatIcon}>☀️</Text>
            <Text style={styles.sunStatPct}>{sunStat.pct}%</Text>
            <Text style={[styles.sunStatDot, { color: theme.textTertiary }]}>·</Text>
            <Text style={[styles.sunStatHours, { color: theme.textSecondary }]}>
              {sunStat.hours.toString().replace('.', ',')}h
            </Text>
          </View>
        )}

        {sunLine && (
          <Text style={styles.sunLine} numberOfLines={1}>
            {sunLine}
          </Text>
        )}
      </View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    paddingVertical: SPACING.sm + 2,
    paddingHorizontal: SPACING.md,
    gap: SPACING.md,
  },
  photoWrap: {
    position: 'relative',
  },
  image: {
    width: 72,
    height: 72,
    borderRadius: 10,
    resizeMode: 'cover',
  },
  badge: {
    position: 'absolute',
    left: 4,
    bottom: 4,
    paddingHorizontal: 5,
    paddingVertical: 2,
    borderRadius: 6,
  },
  badgeText: {
    color: '#FFFFFF',
    fontSize: 9,
    fontWeight: '700',
  },
  content: {
    flex: 1,
    minHeight: 72,
    justifyContent: 'center',
    gap: 3,
  },
  topRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  name: {
    fontSize: 14,
    fontWeight: '700',
    flex: 1,
    marginRight: SPACING.sm,
    letterSpacing: -0.2,
  },
  rating: {
    fontSize: 12,
    fontWeight: '700',
  },
  ratingCount: {
    fontSize: 11,
    color: '#888888',
    fontWeight: '500',
  },
  subtitle: {
    fontSize: 11,
    fontWeight: '400',
  },
  description: {
    fontSize: 11,
    lineHeight: 14,
    fontWeight: '400',
  },
  sunLine: {
    fontSize: 11,
    color: '#F5A623',
    fontWeight: '700',
  },
  sunStatRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    marginTop: 1,
  },
  sunStatIcon: {
    fontSize: 12,
  },
  sunStatPct: {
    fontSize: 12,
    fontWeight: '700',
    color: '#F5A623',
  },
  sunStatDot: {
    fontSize: 12,
    fontWeight: '700',
    marginHorizontal: 1,
  },
  sunStatHours: {
    fontSize: 11,
    fontWeight: '500',
  },
});
