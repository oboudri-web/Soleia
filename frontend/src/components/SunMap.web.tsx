/**
 * Soleia - SunMap (web fallback)
 * Rendu custom en preview web (sans react-native-maps qui casse le bundler).
 * - Markers Soleia positionnés en absolute par projection lat/lng → x/y
 * - Clustering via supercluster pour performance sur 700+ établissements
 */
import React, { useMemo, useState, useCallback } from 'react';
import { View, Text, StyleSheet, Dimensions, TouchableOpacity } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import Supercluster from 'supercluster';
import TerraceMarker from './TerraceMarker';
import { useTheme } from '../ThemeContext';
import type { Terrace } from '../api';
import { SPACING, RADIUS } from '../theme';

const { width: SCREEN_WIDTH } = Dimensions.get('window');

type Props = {
  terraces: Terrace[];
  center: { lat: number; lng: number };
  selectedId?: string | null;
  onMarkerPress: (terrace: Terrace) => void;
  userLocation?: { lat: number; lng: number } | null;
  focusCoords?: { lat: number; lng: number } | null;
  forceDark?: boolean;
  onRegionChange?: (bbox: {
    lat_min: number;
    lat_max: number;
    lng_min: number;
    lng_max: number;
    zoom: number;
  }) => void;
  shadowPolygons?: Array<Array<[number, number]>>;
};

export default function SunMap({
  terraces,
  center,
  selectedId,
  onMarkerPress,
  userLocation,
  focusCoords,
  forceDark,
}: Props) {
  // Note: onRegionChange ignoré sur web (pas de vraie région, zoom contrôlé via pills)
  const { theme, isDark: sysDark } = useTheme();
  const isDark = forceDark ?? sysDark;
  // Simulated zoom (web preview can cycle via +/-)
  const [zoom, setZoom] = useState(13);

  const pad = 0.005;
  let minLat = center.lat - pad;
  let maxLat = center.lat + pad;
  let minLng = center.lng - pad;
  let maxLng = center.lng + pad;
  terraces.forEach((t) => {
    minLat = Math.min(minLat, t.lat);
    maxLat = Math.max(maxLat, t.lat);
    minLng = Math.min(minLng, t.lng);
    maxLng = Math.max(maxLng, t.lng);
  });
  const latPad = Math.max((maxLat - minLat) * 0.15, 0.005);
  const lngPad = Math.max((maxLng - minLng) * 0.15, 0.005);
  minLat -= latPad;
  maxLat += latPad;
  minLng -= lngPad;
  maxLng += lngPad;

  const mapHeight = 600;
  const mapWidth = SCREEN_WIDTH;

  const project = (lat: number, lng: number) => {
    const x = ((lng - minLng) / (maxLng - minLng)) * mapWidth;
    const y = ((maxLat - lat) / (maxLat - minLat)) * mapHeight;
    return { x, y };
  };

  // Supercluster index
  const clusterIndex = useMemo(() => {
    const idx = new Supercluster<
      { terrace: Terrace },
      { point_count: number; sunny: number }
    >({
      radius: 60,
      maxZoom: 14,
      minPoints: 3,
      map: (props: any) => ({ sunny: props.terrace.sun_status === 'sunny' ? 1 : 0 }),
      reduce: (acc: any, props: any) => {
        acc.sunny = (acc.sunny || 0) + (props.sunny || 0);
      },
    });
    const points = terraces.map((t) => ({
      type: 'Feature' as const,
      properties: { terrace: t },
      geometry: { type: 'Point' as const, coordinates: [t.lng, t.lat] as [number, number] },
    }));
    idx.load(points);
    return idx;
  }, [terraces]);

  const clusters = useMemo(() => {
    try {
      return clusterIndex.getClusters([minLng, minLat, maxLng, maxLat], zoom);
    } catch {
      return [];
    }
  }, [clusterIndex, minLng, minLat, maxLng, maxLat, zoom]);

  const onClusterPress = useCallback(
    (clusterId: number) => {
      try {
        const expansionZoom = clusterIndex.getClusterExpansionZoom(clusterId);
        setZoom(Math.min(18, expansionZoom + 1));
      } catch {
        setZoom((z) => Math.min(18, z + 2));
      }
    },
    [clusterIndex],
  );

  const gradientColors = isDark
    ? (['#0A0E1A', '#1A1F2E', '#2A2F3E'] as const)
    : (['#E8F0F5', '#F7F5F0', '#FAE8D0'] as const);

  return (
    <View style={StyleSheet.absoluteFill} testID="sun-map-web">
      <LinearGradient colors={gradientColors} style={StyleSheet.absoluteFill} />

      <View style={StyleSheet.absoluteFill}>
        {[0.25, 0.5, 0.75].map((p) => (
          <View
            key={`h-${p}`}
            style={[
              styles.gridLine,
              {
                top: mapHeight * p,
                width: mapWidth,
                height: 1,
                backgroundColor: isDark ? '#FFFFFF15' : '#00000008',
              },
            ]}
          />
        ))}
        {[0.25, 0.5, 0.75].map((p) => (
          <View
            key={`v-${p}`}
            style={[
              styles.gridLine,
              {
                left: mapWidth * p,
                top: 0,
                width: 1,
                height: mapHeight,
                backgroundColor: isDark ? '#FFFFFF15' : '#00000008',
              },
            ]}
          />
        ))}
      </View>

      {userLocation && (() => {
        const pos = project(userLocation.lat, userLocation.lng);
        return (
          <View
            style={[
              styles.userDot,
              { left: pos.x - 10, top: pos.y - 10, backgroundColor: '#007AFF' },
            ]}
          />
        );
      })()}

      {clusters.map((c: any) => {
        const [lng, lat] = c.geometry.coordinates;
        const pos = project(lat, lng);
        if (c.properties && c.properties.cluster) {
          const count = c.properties.point_count as number;
          const sunny = (c.properties.sunny as number) || 0;
          const clusterId = c.id as number;
          const size = Math.min(68, 36 + Math.log2(count) * 6);
          return (
            <TouchableOpacity
              key={`cluster-${clusterId}`}
              activeOpacity={0.85}
              onPress={() => onClusterPress(clusterId)}
              style={{
                position: 'absolute',
                left: pos.x - size / 2,
                top: pos.y - size / 2,
                width: size,
                height: size,
                borderRadius: size / 2,
                backgroundColor: '#F5A623',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <View
                style={{
                  width: size - 10,
                  height: size - 10,
                  borderRadius: (size - 10) / 2,
                  backgroundColor: '#FFFFFF',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexDirection: 'row',
                }}
              >
                <Text style={styles.clusterSunnyText}>{sunny}</Text>
                <Text style={styles.clusterTotalText}>/{count}</Text>
              </View>
            </TouchableOpacity>
          );
        }
        const t: Terrace = c.properties.terrace;
        return (
          <View
            key={t.id}
            style={{
              position: 'absolute',
              left: pos.x - 22,
              top: pos.y - 22,
            }}
          >
            <TerraceMarker
              status={t.sun_status}
              type={t.type}
              selected={selectedId === t.id}
              verified={t.has_terrace_confirmed !== false}
              onPress={() => onMarkerPress(t)}
            />
          </View>
        );
      })}

      {/* Zoom controls (web preview only) */}
      <View style={styles.zoomControls}>
        <TouchableOpacity
          onPress={() => setZoom((z) => Math.min(18, z + 1))}
          style={[styles.zoomBtn, { backgroundColor: theme.surface }]}
        >
          <Ionicons name="add" size={20} color={theme.primary} />
        </TouchableOpacity>
        <TouchableOpacity
          onPress={() => setZoom((z) => Math.max(8, z - 1))}
          style={[styles.zoomBtn, { backgroundColor: theme.surface }]}
        >
          <Ionicons name="remove" size={20} color={theme.primary} />
        </TouchableOpacity>
      </View>

      <View style={styles.attribution}>
        <Ionicons name="sunny" size={14} color={theme.primary} />
        <Text style={[styles.attributionText, { color: theme.textSecondary }]}>Soleia</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  gridLine: { position: 'absolute' },
  userDot: {
    position: 'absolute',
    width: 20,
    height: 20,
    borderRadius: 10,
    borderWidth: 3,
    borderColor: '#FFFFFF',
    shadowColor: '#007AFF',
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.5,
    shadowRadius: 8,
    elevation: 8,
  },
  clusterSunnyText: {
    fontSize: 15,
    fontWeight: '800',
    color: '#F5A623',
    letterSpacing: -0.3,
  },
  clusterTotalText: {
    fontSize: 10,
    fontWeight: '600',
    color: '#888',
    letterSpacing: -0.2,
    marginLeft: 1,
  },
  zoomControls: {
    position: 'absolute',
    right: SPACING.md,
    top: SPACING.md,
    gap: 6,
  },
  zoomBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.12,
    shadowRadius: 6,
    elevation: 4,
  },
  attribution: {
    position: 'absolute',
    bottom: SPACING.md,
    right: SPACING.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: 'rgba(255,255,255,0.8)',
    paddingHorizontal: SPACING.sm,
    paddingVertical: 4,
    borderRadius: RADIUS.pill,
  },
  attributionText: { fontSize: 10, fontWeight: '600' },
});
