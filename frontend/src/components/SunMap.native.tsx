/**
 * Soleia — SunMap (native: Mapbox GL via @rnmapbox/maps).
 *
 * Migrated from Google Maps (react-native-maps + PROVIDER_GOOGLE) to Mapbox :
 *  - bâtiments 3D extrudés natifs via FillExtrusionLayer sur `composite` source
 *  - markers React custom via MarkerView
 *  - polygones d'ombre via ShapeSource + FillLayer (support rgba propre)
 *  - styles dark/light natifs Mapbox
 *  - clustering via supercluster (calcul JS, rendu via MarkerView)
 */
import React, { useMemo, useRef, useEffect, useState, useCallback } from 'react';
import { View, StyleSheet, Text, TouchableOpacity } from 'react-native';
import Mapbox, {
  MapView,
  Camera,
  MarkerView,
  ShapeSource,
  FillLayer,
  LineLayer,
  FillExtrusionLayer,
  StyleURL,
  UserLocation,
} from '@rnmapbox/maps';
import Supercluster from 'supercluster';
import TerraceMarker from './TerraceMarker';
import { useTheme } from '../ThemeContext';
import type { Terrace } from '../api';

// ─── Token d'accès public Mapbox (runtime, sécurisable par domaine) ───────────
// Fallback hardcodé : un pk.* est public par design, sa sécurité passe par les
// URL/bundle restrictions côté Mapbox. On le hardcode pour garantir l'init même
// si EAS ne propage pas la variable EXPO_PUBLIC_* au runtime du bundle JS iOS.
const MAPBOX_TOKEN_FALLBACK = ''; // Mettre votre pk.* Mapbox ici si vous voulez un fallback hardcodé
const MAPBOX_TOKEN = process.env.EXPO_PUBLIC_MAPBOX_TOKEN || MAPBOX_TOKEN_FALLBACK;

console.log(
  `[mapbox] init — token=${MAPBOX_TOKEN ? MAPBOX_TOKEN.slice(0, 12) + '…(' + MAPBOX_TOKEN.length + ')' : 'MISSING'}, source=${process.env.EXPO_PUBLIC_MAPBOX_TOKEN ? 'env' : 'fallback'}`,
);

try {
  Mapbox.setAccessToken(MAPBOX_TOKEN);
  // Désactive la télémétrie : sur iOS, le ping initial peut bloquer le rendu si
  // pas de réseau ou si Mapbox events.mapbox.com est joignable lentement.
  if (typeof (Mapbox as any).setTelemetryEnabled === 'function') {
    (Mapbox as any).setTelemetryEnabled(false);
  }
  // Indique explicitement qu'on utilise les serveurs Mapbox (pas MapLibre).
  if (typeof (Mapbox as any).setWellKnownTileServer === 'function') {
    (Mapbox as any).setWellKnownTileServer('Mapbox');
  }
  console.log('[mapbox] init OK');
} catch (e) {
  console.error('[mapbox] init FAILED:', e);
}

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
  /** Polygones d'ombres legacy (OSM custom). Désactivés par défaut depuis qu'on
   *  utilise le directional light natif de Mapbox Standard v12. Réactivable via
   *  `enableLegacyShadows={true}` si on détecte des bâtiments OSM absents des
   *  tiles vectorielles Mapbox. */
  shadowPolygons?: Array<Array<[number, number]>>;
  enableLegacyShadows?: boolean;
  /** Minutes depuis 0h (0–1440) pilotant le preset lumineux Mapbox.
   *  Le slider d'heure update cette prop → le directional light bouge → les
   *  ombres natives sur les bâtiments 3D suivent en temps réel. */
  currentMinutes?: number;
};

// Convertit une bbox Mapbox (ne, sw) en notre format {lat_min,lat_max,...,zoom}
function buildBbox(bounds: number[][], zoom: number) {
  // bounds = [[neLng, neLat], [swLng, swLat]]
  const [ne, sw] = bounds;
  return {
    lat_min: Math.min(ne[1], sw[1]),
    lat_max: Math.max(ne[1], sw[1]),
    lng_min: Math.min(ne[0], sw[0]),
    lng_max: Math.max(ne[0], sw[0]),
    zoom: Math.round(zoom),
  };
}

export default function SunMap({
  terraces,
  center,
  selectedId,
  onMarkerPress,
  userLocation,
  focusCoords,
  forceDark,
  onRegionChange,
  shadowPolygons,
  enableLegacyShadows = false,
  currentMinutes,
}: Props) {
  const { isDark } = useTheme();
  const darkMap = forceDark ?? isDark;
  // Style Mapbox Standard v12 — contient nativement :
  //   • bâtiments 3D extrudés (couche `building` avec fill-extrusion)
  //   • sky atmosphérique
  //   • lighting & ombres ambiantes
  //   • route hierarchy à toutes les échelles
  // Pré-tesselé + caché au niveau tile = ~0% GPU custom de notre côté.
  const styleURL = darkMap
    ? 'mapbox://styles/mapbox/standard'
    : 'mapbox://styles/mapbox/standard';

  const mapRef = useRef<MapView>(null);
  const cameraRef = useRef<Camera>(null);

  const [currentZoom, setCurrentZoom] = useState(14);
  const [currentBbox, setCurrentBbox] = useState<{
    lat_min: number; lat_max: number; lng_min: number; lng_max: number;
  }>({
    lat_min: center.lat - 0.02,
    lat_max: center.lat + 0.02,
    lng_min: center.lng - 0.02,
    lng_max: center.lng + 0.02,
  });

  // Fly to focusCoords when it changes
  useEffect(() => {
    if (focusCoords && cameraRef.current) {
      cameraRef.current.setCamera({
        centerCoordinate: [focusCoords.lng, focusCoords.lat],
        zoomLevel: 16,
        pitch: 45,
        animationDuration: 800,
      });
    }
  }, [focusCoords?.lat, focusCoords?.lng]);

  // Diagnostic log — polygones d'ombre
  useEffect(() => {
    const count = shadowPolygons?.length ?? 0;
    if (count > 0) {
      console.log(
        `[shadows.render] ✅ ${count} FillLayer features — first has ${shadowPolygons![0].length} points, e.g. ${JSON.stringify(shadowPolygons![0][0])}`,
      );
    } else {
      console.log('[shadows.render] 0 polygons to render (array empty)');
    }
  }, [shadowPolygons]);

  // ─── Mapbox Standard v12 — directional light driven by slider time ─────────
  // Le style `mapbox/standard` v12 cast de vraies ombres GPU sur les bâtiments
  // 3D selon un `lightPreset`. On bind la prop `currentMinutes` (du slider) à
  // ce preset avec un debounce 300ms pour ne pas saturer le shader sur drag.
  // Mapping :
  //   • <  6h  → night
  //   •  6–9h  → dawn
  //   •  9–18h → day
  //   • 18–21h → dusk
  //   • > 21h  → night
  function pickLightPreset(min: number): 'dawn' | 'day' | 'dusk' | 'night' {
    const h = min / 60;
    if (h < 6) return 'night';
    if (h < 9) return 'dawn';
    if (h < 18) return 'day';
    if (h < 21) return 'dusk';
    return 'night';
  }
  const [lightPreset, setLightPreset] = useState<'dawn' | 'day' | 'dusk' | 'night'>(
    pickLightPreset(currentMinutes ?? new Date().getHours() * 60 + new Date().getMinutes()),
  );
  // Tracks when the basemap style import is actually loaded — only after this
  // can `setStyleImportConfigProperty('basemap', ...)` actually take effect on
  // iOS. Calling it earlier silently fails and the default `day` preset stays
  // — which on some iOS builds defaults to `night` if the device is in dark
  // mode at the OS level.
  const [styleLoaded, setStyleLoaded] = useState(false);

  // Helper: imperatively apply a light preset on the basemap import.
  // Tries multiple known method names across @rnmapbox/maps 10.x versions.
  const applyLightPreset = useCallback((target: 'dawn' | 'day' | 'dusk' | 'night') => {
    const ref: any = mapRef.current;
    if (!ref) {
      console.log(`[mapbox.light] applyLightPreset(${target}) — mapRef.current is null, skipping`);
      return false;
    }
    const methods = [
      'setStyleImportConfigProperty', // 10.1+
      'setMapStyleImportConfigProperty', // alt naming on some forks
    ];
    for (const m of methods) {
      if (typeof ref[m] === 'function') {
        try {
          ref[m]('basemap', 'lightPreset', target);
          console.log(`[mapbox.light] ✅ ${m}('basemap','lightPreset','${target}')`);
          return true;
        } catch (e) {
          console.warn(`[mapbox.light] ${m} threw:`, e);
        }
      }
    }
    console.warn(
      `[mapbox.light] ❌ no setStyleImportConfigProperty method found on mapRef. Available keys: ${Object.keys(ref).slice(0, 12).join(',')}`,
    );
    return false;
  }, []);

  // 1) When style finishes loading, immediately push the *current* preset.
  //    This is the moment the API actually takes effect.
  useEffect(() => {
    if (!styleLoaded) return;
    console.log(`[mapbox.light] style loaded → forcing initial preset='${lightPreset}'`);
    applyLightPreset(lightPreset);
  }, [styleLoaded, lightPreset, applyLightPreset]);

  // 2) When the slider moves, recompute target + apply (debounced 300ms).
  //    We *always* call the API even if target===lightPreset, in case the
  //    initial style load undid it.
  useEffect(() => {
    if (currentMinutes == null) return;
    const target = pickLightPreset(currentMinutes);
    const t = setTimeout(() => {
      if (target !== lightPreset) {
        setLightPreset(target);
        console.log(
          `[mapbox.light] slider preset → ${target} (min=${Math.round(currentMinutes)})`,
        );
      }
      if (styleLoaded) {
        applyLightPreset(target);
      }
    }, 300);
    return () => clearTimeout(t);
  }, [currentMinutes, lightPreset, styleLoaded, applyLightPreset]);

  // Supercluster pour les markers
  const clusterIndex = useMemo(() => {
    const idx = new Supercluster({ radius: 50, maxZoom: 16, minPoints: 3 });
    idx.load(
      terraces.map((t) => ({
        type: 'Feature' as const,
        geometry: { type: 'Point' as const, coordinates: [t.lng, t.lat] },
        properties: {
          id: t.id,
          sunny: t.sun_status === 'sunny' ? 1 : 0,
          terrace: t,
        },
      })),
    );
    return idx;
  }, [terraces]);

  const clusters = useMemo(() => {
    const { lng_min, lat_min, lng_max, lat_max } = currentBbox;
    return clusterIndex.getClusters(
      [lng_min, lat_min, lng_max, lat_max],
      currentZoom,
    );
  }, [clusterIndex, currentBbox, currentZoom]);

  // Shadow polygons → FeatureCollection GeoJSON
  const shadowFeatureCollection = useMemo(() => {
    if (!shadowPolygons || shadowPolygons.length === 0) {
      return { type: 'FeatureCollection' as const, features: [] };
    }
    return {
      type: 'FeatureCollection' as const,
      features: shadowPolygons.map((poly, idx) => ({
        type: 'Feature' as const,
        id: idx,
        geometry: {
          type: 'Polygon' as const,
          // Mapbox utilise [lng, lat], notre backend retourne [lat, lng]
          coordinates: [poly.map(([lat, lng]) => [lng, lat] as [number, number])],
        },
        properties: {},
      })),
    };
  }, [shadowPolygons]);

  const onCameraChanged = useCallback(
    async (state: any) => {
      try {
        const zoom = state.properties?.zoom ?? 14;
        setCurrentZoom(Math.round(zoom));
        if (mapRef.current) {
          const bounds = await mapRef.current.getVisibleBounds();
          const bbox = buildBbox(bounds, zoom);
          setCurrentBbox({
            lat_min: bbox.lat_min,
            lat_max: bbox.lat_max,
            lng_min: bbox.lng_min,
            lng_max: bbox.lng_max,
          });
          onRegionChange?.(bbox);
        }
      } catch (e) {
        // ignore
      }
    },
    [onRegionChange],
  );

  return (
    <View style={styles.container}>
      <MapView
        ref={mapRef}
        style={StyleSheet.absoluteFill}
        styleURL={styleURL}
        logoEnabled={false}
        attributionEnabled={false}
        scaleBarEnabled={false}
        compassEnabled={false}
        // Charge GPU divisée par ~3 grâce au style `standard` (3D buildings
        // natifs et caches au niveau tile). On peut donc rétablir pitch+rotate
        // pour le feeling 3D recherché.
        scrollEnabled
        zoomEnabled
        pitchEnabled
        rotateEnabled
        onCameraChanged={onCameraChanged}
        onDidFinishLoadingStyle={() => {
          console.log(`[mapbox.style] ✅ style loaded — URL='${styleURL}'`);
          setStyleLoaded(true);
        }}
        onDidFinishLoadingMap={() => {
          console.log('[mapbox.map] ✅ map fully loaded (tiles + style)');
        }}
        onDidFailLoadingMap={() => {
          console.warn('[mapbox.map] ❌ map failed to load — check token / network');
        }}
        testID="sun-map-native"
      >
        <Camera
          ref={cameraRef}
          defaultSettings={{
            centerCoordinate: [center.lng, center.lat],
            zoomLevel: 14,
            pitch: 45,
          }}
          animationMode="flyTo"
          animationDuration={1000}
        />

        {/* Bâtiments 3D : fournis nativement par le style `mapbox/standard`
            (couche `building` avec fill-extrusion intégrée + sky atmosphérique
            + lighting). Aucun layer custom ici → moins de code, moins de
            surface de bug, GPU heureux.
            
            Les ombres GPU réelles sur les bâtiments 3D sont pilotées par
            `lightPreset` (voir useEffect plus haut) — pas de polygone à
            transmettre, le shader Mapbox les calcule en temps réel. */}

        {/* Ombres legacy OSM — désactivées par défaut, gardées en fallback */}
        {enableLegacyShadows && shadowFeatureCollection.features.length > 0 && (
          <ShapeSource id="soleia-shadows" shape={shadowFeatureCollection as any}>
            <FillLayer
              id="soleia-shadows-fill"
              style={{
                fillColor: 'rgba(20, 20, 30, 0.45)',
                fillOutlineColor: 'rgba(20, 20, 30, 0.55)',
              }}
            />
          </ShapeSource>
        )}

        {/* User location (puck bleu natif Mapbox) */}
        {userLocation && (
          <UserLocation
            visible
            androidRenderMode="normal"
            showsUserHeadingIndicator
          />
        )}

        {/* Clusters + markers individuels */}
        {clusters.map((c: any) => {
          const [lng, lat] = c.geometry.coordinates;
          if (c.properties && c.properties.cluster) {
            const count = c.properties.point_count as number;
            const sunny = (c.properties.sunny as number) || 0;
            const clusterId = c.id as number;
            const size = Math.min(68, 36 + Math.log2(count) * 6);
            return (
              <MarkerView
                key={`cluster-${clusterId}`}
                coordinate={[lng, lat]}
                anchor={{ x: 0.5, y: 0.5 }}
                allowOverlap
              >
                <TouchableOpacity
                  activeOpacity={0.85}
                  onPress={() => {
                    if (cameraRef.current) {
                      cameraRef.current.setCamera({
                        centerCoordinate: [lng, lat],
                        zoomLevel: Math.min(17, currentZoom + 2),
                        animationDuration: 500,
                      });
                    }
                  }}
                  style={[
                    styles.cluster,
                    {
                      width: size,
                      height: size,
                      backgroundColor: darkMap ? '#F5A623' : '#FFFFFF',
                      borderColor: '#F5A623',
                    },
                  ]}
                >
                  <Text style={[styles.clusterTop, { color: darkMap ? '#fff' : '#F5A623' }]}>
                    {sunny}
                  </Text>
                  <Text style={[styles.clusterBottom, { color: darkMap ? '#fff' : '#333' }]}>
                    /{count}
                  </Text>
                </TouchableOpacity>
              </MarkerView>
            );
          }
          // Marker individuel
          const terrace = c.properties?.terrace as Terrace;
          if (!terrace) return null;
          return (
            <MarkerView
              key={`terrace-${terrace.id}`}
              coordinate={[lng, lat]}
              anchor={{ x: 0.5, y: 0.5 }}
              allowOverlap={false}
            >
              <TouchableOpacity
                activeOpacity={0.85}
                onPress={() => onMarkerPress(terrace)}
              >
                <TerraceMarker
                  terrace={terrace}
                  selected={selectedId === terrace.id}
                />
              </TouchableOpacity>
            </MarkerView>
          );
        })}
      </MapView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  cluster: {
    borderRadius: 999,
    borderWidth: 2,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.2,
    shadowRadius: 8,
    elevation: 6,
  },
  clusterTop: { fontSize: 16, fontWeight: '800', letterSpacing: -0.3 },
  clusterBottom: { fontSize: 11, fontWeight: '600', opacity: 0.85, marginTop: -2 },
});
