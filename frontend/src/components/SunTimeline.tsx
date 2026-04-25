/**
 * Soleia - SunTimeline
 * Timeline visuelle 6h-22h : segments jaunes (soleil) + gris (ombre) par tranche de 30 min,
 * indicateur vertical pour l'heure sélectionnée (tap-to-scrub), bouton Maintenant.
 */
import React, { useMemo, useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  GestureResponderEvent,
  LayoutChangeEvent,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../ThemeContext';
import { SPACING, RADIUS } from '../theme';
import { formatTimeFr, hhmmToFr } from '../utils/time';

type SunnyRange = { start: string; end: string };

type Props = {
  sunnyRanges: SunnyRange[]; // hh:mm format
  currentMinutes: number; // 0-24*60
  onChange: (minutes: number) => void;
  isLive: boolean;
  onLive: () => void;
};

const START_HOUR = 6;
const END_HOUR = 22;
const STEP_MIN = 30;
const TOTAL_MIN = (END_HOUR - START_HOUR) * 60; // 960
const SEGMENTS = TOTAL_MIN / STEP_MIN; // 32 segments

function hhmmToMin(s: string): number {
  const [h, m] = s.split(':').map(Number);
  return h * 60 + (m || 0);
}

export default function SunTimeline({
  sunnyRanges,
  currentMinutes,
  onChange,
  isLive,
  onLive,
}: Props) {
  const { theme, isDark } = useTheme();
  const [trackWidth, setTrackWidth] = useState(0);

  // Precompute sunny bit for each segment
  const segmentIsSunny = useMemo(() => {
    const result = new Array(SEGMENTS).fill(false);
    sunnyRanges.forEach((r) => {
      const sMin = hhmmToMin(r.start);
      const eMin = hhmmToMin(r.end);
      for (let i = 0; i < SEGMENTS; i++) {
        const segStart = START_HOUR * 60 + i * STEP_MIN;
        const segEnd = segStart + STEP_MIN;
        if (segStart < eMin && segEnd > sMin) {
          result[i] = true;
        }
      }
    });
    return result;
  }, [sunnyRanges]);

  const sunnyCount = segmentIsSunny.filter(Boolean).length;
  const sunnyMinutes = sunnyCount * STEP_MIN;
  const sunnyHours = Math.floor(sunnyMinutes / 60);
  const sunnyRemain = sunnyMinutes % 60;

  // Current position ratio (clamped to 6h-22h)
  const clamped = Math.max(START_HOUR * 60, Math.min(END_HOUR * 60, currentMinutes));
  const ratio = (clamped - START_HOUR * 60) / TOTAL_MIN;

  const onPressTrack = useCallback(
    (e: GestureResponderEvent) => {
      if (!trackWidth) return;
      const x = e.nativeEvent.locationX;
      const r = Math.max(0, Math.min(1, x / trackWidth));
      const rawMin = START_HOUR * 60 + r * TOTAL_MIN;
      const snapped = Math.round(rawMin / STEP_MIN) * STEP_MIN;
      onChange(snapped);
    },
    [trackWidth, onChange],
  );

  const onLayout = useCallback((e: LayoutChangeEvent) => {
    setTrackWidth(e.nativeEvent.layout.width);
  }, []);

  const sunnyColor = theme.primary;
  const shadeColor = isDark ? '#2A2A2A' : '#EAEAEA';

  // Find the main sunny range text: first sunny segment start + last end
  const firstSunny = segmentIsSunny.findIndex(Boolean);
  const lastSunny = segmentIsSunny.length - 1 - [...segmentIsSunny].reverse().findIndex(Boolean);
  const hasAnySunny = firstSunny !== -1;
  const firstStartMin = hasAnySunny ? START_HOUR * 60 + firstSunny * STEP_MIN : null;
  const lastEndMin = hasAnySunny ? START_HOUR * 60 + (lastSunny + 1) * STEP_MIN : null;

  return (
    <View style={[styles.card, { backgroundColor: theme.surface, borderColor: theme.border }]}>
      <View style={styles.header}>
        <View style={styles.headerLeft}>
          <Ionicons name="sunny" size={18} color={theme.primary} />
          <Text style={[styles.title, { color: theme.text }]}>Journée de soleil</Text>
        </View>
        {hasAnySunny ? (
          <View style={[styles.totalPill, { backgroundColor: theme.primary }]}>
            <Text style={styles.totalPillText}>
              {sunnyHours > 0 ? `${sunnyHours}h` : ''}
              {sunnyRemain > 0 ? sunnyRemain.toString().padStart(sunnyHours > 0 ? 2 : 1, '0') : sunnyHours === 0 ? '0' : ''}
              {' de soleil'}
            </Text>
          </View>
        ) : null}
      </View>

      {/* Timeline track */}
      <TouchableOpacity
        activeOpacity={0.9}
        onPress={onPressTrack}
        onLayout={onLayout}
        style={styles.trackArea}
        testID="sun-timeline-track"
      >
        <View style={styles.segments}>
          {segmentIsSunny.map((sunny, i) => (
            <View
              key={i}
              style={[
                styles.segment,
                {
                  backgroundColor: sunny ? sunnyColor : shadeColor,
                  marginRight: i < SEGMENTS - 1 ? 1 : 0,
                },
              ]}
            />
          ))}
        </View>

        {/* Current indicator */}
        {trackWidth > 0 ? (
          <View
            pointerEvents="none"
            style={[
              styles.indicator,
              {
                left: Math.max(0, Math.min(trackWidth - 4, ratio * trackWidth - 2)),
                backgroundColor: theme.text,
              },
            ]}
          >
            <View style={[styles.indicatorBubble, { backgroundColor: theme.text }]}>
              <Text style={styles.indicatorText}>
                {isLive ? 'NOW' : formatTimeFr(clamped)}
              </Text>
            </View>
          </View>
        ) : null}
      </TouchableOpacity>

      {/* Hour labels */}
      <View style={styles.labelsRow}>
        {[6, 10, 14, 18, 22].map((h) => (
          <Text key={h} style={[styles.label, { color: theme.textTertiary }]}>
            {h}h
          </Text>
        ))}
      </View>

      <View style={styles.footer}>
        {hasAnySunny && firstStartMin !== null && lastEndMin !== null ? (
          <Text style={[styles.summary, { color: theme.textSecondary }]}>
            Soleil de{' '}
            <Text style={[styles.summaryStrong, { color: theme.text }]}>
              {formatTimeFr(firstStartMin)}
            </Text>
            {' à '}
            <Text style={[styles.summaryStrong, { color: theme.text }]}>
              {formatTimeFr(lastEndMin)}
            </Text>
          </Text>
        ) : (
          <Text style={[styles.summary, { color: theme.textSecondary }]}>
            Pas de soleil aujourd'hui sur cette terrasse
          </Text>
        )}

        {!isLive ? (
          <TouchableOpacity
            testID="btn-timeline-live"
            onPress={onLive}
            activeOpacity={0.85}
            style={[styles.liveBtn, { backgroundColor: theme.text }]}
          >
            <Ionicons name="radio" size={11} color="#FFFFFF" />
            <Text style={styles.liveBtnText}>Maintenant</Text>
          </TouchableOpacity>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    marginHorizontal: SPACING.md,
    marginBottom: SPACING.md,
    padding: SPACING.md,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: SPACING.sm + 2,
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
  },
  title: {
    fontSize: 16,
    fontWeight: '800',
    letterSpacing: -0.3,
  },
  totalPill: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 999,
  },
  totalPillText: {
    color: '#FFF',
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 0.2,
  },
  trackArea: {
    position: 'relative',
    paddingVertical: 12,
  },
  segments: {
    flexDirection: 'row',
    height: 22,
    borderRadius: 6,
    overflow: 'hidden',
  },
  segment: {
    flex: 1,
    height: '100%',
  },
  indicator: {
    position: 'absolute',
    top: 4,
    bottom: 4,
    width: 4,
    borderRadius: 2,
  },
  indicatorBubble: {
    position: 'absolute',
    top: -28,
    left: -18,
    width: 40,
    paddingVertical: 3,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  indicatorText: {
    color: '#FFF',
    fontSize: 9,
    fontWeight: '800',
    letterSpacing: 0.3,
  },
  labelsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 2,
  },
  label: {
    fontSize: 10,
    fontWeight: '600',
  },
  footer: {
    marginTop: SPACING.sm + 2,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: SPACING.sm,
    flexWrap: 'wrap',
  },
  summary: {
    fontSize: 12,
    fontWeight: '500',
    flexShrink: 1,
  },
  summaryStrong: {
    fontWeight: '800',
  },
  liveBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 999,
  },
  liveBtnText: {
    color: '#FFF',
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 0.3,
  },
});
