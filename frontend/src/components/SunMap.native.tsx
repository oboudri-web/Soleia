/**
 * Soleia - SunMap (native iOS/Android via @rnmapbox/maps).
 *
 * Architecture (PR A):
 *   - <Mapbox.MapView>            : carte native (style satellite/streets)
 *   - <Mapbox.Camera>             : contrôle caméra (centre, zoom, focus)
 *   - <Mapbox.UserLocation>       : pin bleu utilisateur en temps réel
 *   - <Mapbox.ShapeSource>        : source GeoJSON avec clustering NATIF
 *       └─ <Mapbox.CircleLayer>   : cercles pour clusters
 *       └─ <Mapbox.SymbolLayer>   : nombre dans le cluster
 *       └─ <Mapbox.CircleLayer>   : cercles markers individuels (orange / jaune / gris)
 *
 * PR B (à venir) ajoutera une WebView TRANSPARENTE par-dessus pour ShadeMap.
 *
 * NOTE PR A.1 (debug markers invisibles):
 *   - Properties STRING-based (sunStatus: 'sunny'|'soon'|'shade') au lieu de
 *     numeric flags — plus stable avec @rnmapbox/maps v10 + New Architecture.
 *   - Camera explicite (centerCoordinate + zoomLevel) au lieu de defaultSettings,
 *     car defaultSettings ne s'applique pas toujours en Fabric/iOS.
 *   - onDidFinishLoadingStyle log pour confirmer que le style Mapbox est prêt
 *     avant que les ShapeSource/CircleLayer s'attachent.
 *   - circleStrokeWidth bumped à 3px pour halo bien visible (Retina).
 */
import React, { useEffect, useMemo, useRef, useCallback } from 'react';
import { StyleSheet } from 'react-native';
import Mapbox, {
  MapView,
  Camera,
  ShapeSource,
  CircleLayer,
  SymbolLayer,
  UserLocation,
  StyleURL,
} from '@rnmapbox/maps';
import type { Feature, FeatureCollection, Point } from 'geojson';

import type { Terrace } from '../api';

Mapbox.setAccessToken(process.env.EXPO_PUBLIC_MAPBOX_TOKEN || '');
// Optional perf hints
Mapbox.setTelemetryEnabled(false);

type LatLng = { lat: number; lng: number };

type Props = {
  terraces: Terrace[];
  center: LatLng;
  selectedId: string | null;
  onMarkerPress: (terrace: Terrace) => void;
  userLocation: LatLng | null;
  focusCoords?: LatLng | null;
  forceDark?: boolean;
  onRegionChange?: (info: { lat_min: number; lat_max: number; lng_min: number; lng_max: number; zoom: number }) => void;
  onMarkersUpdate?: (info: { rnSent?: number; webViewReceived?: number; markersRendered?: number }) => void;
  shadowPolygons?: unknown[];
  enableLegacyShadows?: boolean;
  currentMinutes?: number;
};

export default function SunMap({
  terraces,
  center,
  selectedId,
  onMarkerPress,
  userLocation,
  focusCoords,
  forceDark,
  onRegionChange,
  onMarkersUpdate,
}: Props) {
  const mapRef = useRef<MapView | null>(null);
  const cameraRef = useRef<Camera | null>(null);

  // ── Build GeoJSON FeatureCollection from terraces ──────────────────────────
  // Properties sent natively MUST be JSON-serializable primitives. We use
  // string-typed `sunStatus` to avoid any boolean/number coercion across
  // the JSI bridge in New Architecture.
  const featureCollection = useMemo<FeatureCollection<Point>>(() => {
    const features: Feature<Point>[] = [];
    let valid = 0;
    let dropped = 0;
    for (const t of terraces) {
      const lat = Number(t.lat);
      const lng = Number(t.lng);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
        dropped++;
        continue;
      }
      if (lat < -85 || lat > 85 || lng < -180 || lng > 180) {
        dropped++;
        continue;
      }
      valid++;
      // Normalize sun_status to one of: 'sunny' | 'soon' | 'shade'.
      // Backend may emit 'soon_sunny' (legacy alias) — collapse to 'soon'.
      let sunStatus: 'sunny' | 'soon' | 'shade' = 'shade';
      const rawStatus = String(t.sun_status ?? '');
      if (rawStatus === 'sunny') sunStatus = 'sunny';
      else if (rawStatus === 'soon' || rawStatus === 'soon_sunny') sunStatus = 'soon';
      features.push({
        type: 'Feature',
        properties: {
          id: t.id,
          name: t.name,
          sunStatus,
          selected: t.id === selectedId ? 1 : 0,
        },
        geometry: { type: 'Point', coordinates: [lng, lat] },
      });
    }
    // eslint-disable-next-line no-console
    console.log(
      `[SunMap.native] 📍 GeoJSON built: valid=${valid} dropped=${dropped} total=${terraces.length}`,
    );
    onMarkersUpdate?.({ rnSent: valid, webViewReceived: valid, markersRendered: valid });
    return { type: 'FeatureCollection', features };
  }, [terraces, selectedId, onMarkersUpdate]);

  // ── Recenter camera when focusCoords changes (selected pin) ────────────────
  useEffect(() => {
    if (!focusCoords || !cameraRef.current) return;
    cameraRef.current.setCamera({
      centerCoordinate: [focusCoords.lng, focusCoords.lat],
      zoomLevel: 16,
      animationDuration: 600,
    });
  }, [focusCoords]);

  // ── Emit bbox + zoom on every region settle ────────────────────────────────
  const handleCameraChanged = useCallback(
    async (e: { properties: { bounds?: { ne: number[]; sw: number[] }; zoom: number } }) => {
      try {
        const bounds = e?.properties?.bounds;
        if (!bounds) return;
        const ne = bounds.ne;
        const sw = bounds.sw;
        if (!Array.isArray(ne) || !Array.isArray(sw)) return;
        onRegionChange?.({
          lng_min: Math.min(ne[0], sw[0]),
          lng_max: Math.max(ne[0], sw[0]),
          lat_min: Math.min(ne[1], sw[1]),
          lat_max: Math.max(ne[1], sw[1]),
          zoom: e.properties.zoom,
        });
      } catch {
        /* swallow — onCameraChanged sometimes emits without bounds during animations */
      }
    },
    [onRegionChange],
  );

  // ── Press handler on the ShapeSource → either expand cluster or open card ──
  const handleShapePress = useCallback(
    async (e: { features: Feature[] }) => {
      const f = e.features?.[0];
      if (!f) return;
      const props = (f.properties || {}) as Record<string, unknown>;
      // Cluster: expand by zooming in
      if (props.cluster) {
        const coords = (f.geometry as Point).coordinates;
        cameraRef.current?.setCamera({
          centerCoordinate: coords,
          zoomLevel: ((props.cluster_id as number | undefined) ?? 0) > 0 ? undefined : 14,
          animationDuration: 500,
        });
        return;
      }
      // Individual marker: open terrace card
      const id = String(props.id);
      const t = terraces.find((x) => x.id === id);
      if (t) onMarkerPress(t);
    },
    [terraces, onMarkerPress],
  );

  // ── Style/lifecycle log: confirm the Mapbox style is fully loaded ──────────
  const handleDidFinishLoadingStyle = useCallback(() => {
    // eslint-disable-next-line no-console
    console.log('[SunMap.native] 🎨 didFinishLoadingStyle');
  }, []);

  return (
    <MapView
      ref={mapRef}
      style={StyleSheet.absoluteFill}
      styleURL={forceDark ? StyleURL.Dark : StyleURL.Street}
      compassEnabled
      compassPosition={{ top: 88, right: 12 }}
      logoEnabled={false}
      attributionEnabled={false}
      scaleBarEnabled={false}
      onCameraChanged={handleCameraChanged}
      onDidFinishLoadingStyle={handleDidFinishLoadingStyle}
      testID="sun-map-native"
    >
      <Camera
        ref={cameraRef}
        centerCoordinate={[center.lng, center.lat]}
        zoomLevel={13}
        animationMode="easeTo"
        animationDuration={0}
      />

      {userLocation ? <UserLocation visible androidRenderMode="normal" /> : null}

      <ShapeSource
        id="soleia-terraces"
        shape={featureCollection}
        cluster
        clusterRadius={25}
        clusterMaxZoomLevel={14}
        onPress={handleShapePress}
      >
        {/* Cluster bubble (orange ring + warm fill) */}
        <CircleLayer
          id="soleia-clusters"
          filter={['has', 'point_count']}
          style={{
            circleColor: '#F5A623',
            circleStrokeColor: '#FFFFFF',
            circleStrokeWidth: 2,
            circleRadius: [
              'interpolate',
              ['linear'],
              ['get', 'point_count'],
              2, 18,
              50, 30,
              200, 40,
            ],
            circleOpacity: 0.92,
          }}
        />
        {/* Cluster count label */}
        <SymbolLayer
          id="soleia-cluster-count"
          filter={['has', 'point_count']}
          style={{
            textField: ['get', 'point_count_abbreviated'],
            textSize: 13,
            textColor: '#FFFFFF',
            textHaloColor: '#00000033',
            textHaloWidth: 0.4,
            textIgnorePlacement: true,
            textAllowOverlap: true,
          }}
        />
        {/* Individual unclustered markers — solid colored discs.
            We use a `match` expression on string-typed `sunStatus` because it
            ships through the JSI bridge more reliably than `case` + numeric
            flags on @rnmapbox/maps v10 + Fabric. */}
        <CircleLayer
          id="soleia-unclustered"
          filter={['!', ['has', 'point_count']]}
          style={{
            circleRadius: 12,
            circleColor: [
              'match',
              ['get', 'sunStatus'],
              'sunny', '#F5A623',
              'soon',  '#FFD700',
              'shade', '#9E9E9E',
              /* default */ '#FF3B30', // RED fallback → si on voit du rouge
                                       //   = circleColor expression mal évaluée
                                       //   = bug à corriger côté propriétés.
            ],
            circleStrokeColor: '#FFFFFF',
            circleStrokeWidth: 3,
            circleOpacity: 1,
          }}
        />
      </ShapeSource>
    </MapView>
  );
}
