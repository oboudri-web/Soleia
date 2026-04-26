/**
 * Soleia — SunMap (native: WebView + MapLibre GL JS + ShadeMap).
 *
 * Architecture (à la SunSeekr) :
 *   • Une <WebView> plein écran charge un HTML inline qui rend MapLibre +
 *     ShadeMap (mapbox-gl-shadow-simulator) avec terrain MapTiler.
 *   • Les markers de terrasses sont des <View> RN positionnés en absolu
 *     par-dessus la WebView, repositionnés à chaque viewport change via
 *     map.project() côté HTML qui post un message à RN.
 *   • Le slider d'heure côté RN appelle window.setShadeTime(timestamp) via
 *     injectJavaScript avec un debounce 300ms.
 *
 * Avantages :
 *   • Vraies ombres solaires en temps réel sur tout le terrain (ShadeMap).
 *   • Style MapTiler clair, stable, beau.
 *   • Aucun SDK natif tiers à compiler — pas de crash iOS sur les builds EAS.
 *   • Markers RN gardés (gestures natifs, animations, accessibilité).
 */
import React, { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { View, StyleSheet, Text, TouchableOpacity, Platform } from 'react-native';
import { WebView, WebViewMessageEvent } from 'react-native-webview';
import TerraceMarker from './TerraceMarker';
import { MAP_HTML } from './mapHtml';
import type { Terrace } from '../api';

type Props = {
  terraces: Terrace[];
  center: { lat: number; lng: number };
  selectedId?: string | null;
  onMarkerPress: (terrace: Terrace) => void;
  userLocation?: { lat: number; lng: number } | null;
  focusCoords?: { lat: number; lng: number } | null;
  /** @deprecated kept for parent compat — ShadeMap replaces darkMap */
  forceDark?: boolean;
  onRegionChange?: (bbox: {
    lat_min: number;
    lat_max: number;
    lng_min: number;
    lng_max: number;
    zoom: number;
  }) => void;
  /** @deprecated kept for parent compat — ShadeMap replaces backend shadows */
  shadowPolygons?: Array<Array<[number, number]>>;
  /** @deprecated kept for parent compat */
  enableLegacyShadows?: boolean;
  /** Minutes since 0h (0–1440) bound to ShadeMap.setDate via debounce. */
  currentMinutes?: number;
};

type ViewportPoint = {
  id: string;
  x: number; // CSS pixel from top-left of WebView
  y: number;
  sunny: number;
};

type ViewportMessage = {
  type: 'viewport';
  center: { lat: number; lng: number };
  zoom: number;
  bearing: number;
  pitch: number;
  bounds: { lat_min: number; lat_max: number; lng_min: number; lng_max: number };
  points: ViewportPoint[];
};

export default function SunMap({
  terraces,
  center,
  selectedId,
  onMarkerPress,
  userLocation,
  focusCoords,
  onRegionChange,
  currentMinutes,
}: Props) {
  const webRef = useRef<WebView>(null);
  const [points, setPoints] = useState<ViewportPoint[]>([]);
  const [mapReady, setMapReady] = useState(false);
  const [shadeReady, setShadeReady] = useState(false);
  const lastSentTerracesKeyRef = useRef<string>('');
  const shadeDebounceRef = useRef<any>(null);

  // ─── Map ↔ RN bridge: receive viewport + mapReady + errors ─────────────
  const onMessage = useCallback((ev: WebViewMessageEvent) => {
    try {
      const data = JSON.parse(ev.nativeEvent.data);
      switch (data.type) {
        case 'cssInjected':
          console.log(`[soleia.web] css injected (${data.size} bytes)`);
          break;
        case 'maplibreInjected':
          console.log(
            `[soleia.web] maplibre injected (${data.size} bytes, hasGlobal=${data.hasGlobal})`,
          );
          break;
        case 'shadeMapInjected':
          console.log(
            `[soleia.web] shademap injected (${data.size} bytes, hasGlobal=${data.hasGlobal})`,
          );
          break;
        case 'htmlLoaded':
          console.log('[soleia.web] HTML loaded');
          break;
        case 'mapReady':
          console.log('[soleia.web] ✅ MapLibre ready');
          setMapReady(true);
          break;
        case 'shadeMapReady':
          console.log('[soleia.web] ✅ ShadeMap ready');
          setShadeReady(true);
          break;
        case 'layersHidden':
          console.log(
            `[soleia.web] hidden ${data.count}/${data.total} POI/transit layers`,
          );
          break;
        case 'buildings3DAdded':
          console.log(
            `[soleia.web] ✅ 3D buildings layer added (before='${data.beforeLayer}')`,
          );
          break;
        case 'terracesAck':
          console.log(`[soleia.web] terracesAck count=${data.count}`);
          break;
        case 'viewport': {
          const v = data as ViewportMessage;
          setPoints(v.points || []);
          if (onRegionChange) {
            onRegionChange({
              lat_min: v.bounds.lat_min,
              lat_max: v.bounds.lat_max,
              lng_min: v.bounds.lng_min,
              lng_max: v.bounds.lng_max,
              zoom: Math.round(v.zoom),
            });
          }
          break;
        }
        case 'mapError':
          console.warn('[soleia.web] map error:', data.msg);
          break;
        case 'error':
          console.warn('[soleia.web] error:', data.msg);
          break;
        case 'shadeLog':
          console.log('[soleia.web.shade]', data.msg);
          break;
        default:
          break;
      }
    } catch (e) {
      // Non-JSON message — ignore.
    }
  }, [onRegionChange]);

  // ─── Push terraces (+ optional user dot) to the WebView ────────────────
  useEffect(() => {
    if (!mapReady || !webRef.current) {
      console.log(
        `[soleia.rn] skip updateTerraces — mapReady=${mapReady} webRef=${!!webRef.current}`,
      );
      return;
    }
    const slim = terraces
      .filter(
        (t) =>
          typeof t.lat === 'number' &&
          typeof t.lng === 'number' &&
          !isNaN(t.lat) &&
          !isNaN(t.lng),
      )
      .map((t) => ({
        id: t.id,
        lat: t.lat,
        lng: t.lng,
        sun_status: t.sun_status,
      }));
    if (userLocation && typeof userLocation.lat === 'number' && typeof userLocation.lng === 'number') {
      slim.push({
        id: '__user__',
        lat: userLocation.lat,
        lng: userLocation.lng,
        sun_status: 'sunny',
      } as any);
    }
    const key = JSON.stringify(slim.map((t) => `${t.id}:${t.sun_status}`));
    if (key === lastSentTerracesKeyRef.current) {
      // No change — nothing to do.
      return;
    }
    lastSentTerracesKeyRef.current = key;
    const payload = JSON.stringify(slim);
    webRef.current.injectJavaScript(
      `try { window.updateTerraces(${payload}); } catch(e){ window.ReactNativeWebView && window.ReactNativeWebView.postMessage(JSON.stringify({type:'error',msg:'updateTerraces injection failed: '+e.message})); } true;`,
    );
    console.log(
      `[soleia.rn] sent ${slim.length} points to WebView (terraces=${slim.length - (userLocation ? 1 : 0)} + user=${userLocation ? 1 : 0})`,
    );
  }, [terraces, mapReady, userLocation?.lat, userLocation?.lng]);

  // ─── Recenter the map when `center` changes (city switch) ──────────────
  useEffect(() => {
    if (!mapReady || !webRef.current) return;
    if (typeof center?.lat !== 'number' || typeof center?.lng !== 'number') return;
    webRef.current.injectJavaScript(
      `try { window.setCenter(${center.lat}, ${center.lng}, 14); } catch(e){} true;`,
    );
  }, [center?.lat, center?.lng, mapReady]);

  // ─── Fly to focusCoords on demand ──────────────────────────────────────
  useEffect(() => {
    if (!mapReady || !webRef.current || !focusCoords) return;
    webRef.current.injectJavaScript(
      `try { window.flyTo(${focusCoords.lat}, ${focusCoords.lng}, 16); } catch(e){} true;`,
    );
  }, [focusCoords?.lat, focusCoords?.lng, mapReady]);

  // ─── Bind currentMinutes (slider) → ShadeMap.setDate (debounced 300ms) ──
  useEffect(() => {
    if (!shadeReady || !webRef.current || currentMinutes == null) return;
    if (shadeDebounceRef.current) clearTimeout(shadeDebounceRef.current);
    shadeDebounceRef.current = setTimeout(() => {
      const now = new Date();
      const target = new Date(
        now.getFullYear(),
        now.getMonth(),
        now.getDate(),
        Math.floor(currentMinutes / 60),
        currentMinutes % 60,
        0,
        0,
      );
      const ts = target.getTime();
      webRef.current?.injectJavaScript(
        `try { window.setShadeTime(${ts}); } catch(e){} true;`,
      );
    }, 300);
    return () => {
      if (shadeDebounceRef.current) clearTimeout(shadeDebounceRef.current);
    };
  }, [currentMinutes, shadeReady]);

  // ─── User location overlay : a synthetic point with id='__user__' is sent
  // to the WebView alongside the regular terraces (see effect above), and the
  // WebView projects its pixel position back to RN via postMessage. We render
  // it as a blue puck below.

  // Map terrace.id → terrace for quick lookup in the marker render loop
  const terracesById = useMemo(() => {
    const m = new Map<string, Terrace>();
    for (const t of terraces) m.set(t.id, t);
    return m;
  }, [terraces]);

  return (
    <View style={styles.container}>
      <WebView
        ref={webRef}
        style={StyleSheet.absoluteFill}
        originWhitelist={['*']}
        source={{ html: MAP_HTML, baseUrl: 'https://localhost' }}
        javaScriptEnabled
        domStorageEnabled
        allowsInlineMediaPlayback
        mediaPlaybackRequiresUserAction={false}
        onMessage={onMessage}
        // Prevent the WebView from bouncing on iOS (we want pan to feel native)
        bounces={false}
        scrollEnabled={false}
        showsHorizontalScrollIndicator={false}
        showsVerticalScrollIndicator={false}
        // iOS perf: disable HW back-forward cache, use modern WKWebView features
        injectedJavaScriptBeforeContentLoaded={`
          window.__SOLEIA_RN__ = true;
          true;
        `}
        // Don't block on initial render
        startInLoadingState={false}
        // Allow WebGL + CDN scripts
        mixedContentMode="always"
        thirdPartyCookiesEnabled
        cacheEnabled
        testID="sun-map-webview"
      />

      {/* Markers overlay — pointerEvents="box-none" lets pan/zoom gestures
          fall through to the WebView, while individual markers still receive
          tap events. */}
      <View style={StyleSheet.absoluteFill} pointerEvents="box-none">
        {points.map((p) => {
          if (p.id === '__user__') {
            return (
              <View
                key="user-dot"
                pointerEvents="none"
                style={[
                  styles.userDotContainer,
                  { left: p.x - 12, top: p.y - 12 },
                ]}
              >
                <View style={styles.userDotPulse} />
                <View style={styles.userDot} />
              </View>
            );
          }
          const terrace = terracesById.get(p.id);
          if (!terrace) return null;
          return (
            <View
              key={`m-${p.id}`}
              pointerEvents="box-none"
              style={[
                styles.markerContainer,
                { left: p.x - 18, top: p.y - 18 },
              ]}
            >
              <TouchableOpacity
                activeOpacity={0.85}
                onPress={() => onMarkerPress(terrace)}
                hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
              >
                <TerraceMarker
                  terrace={terrace}
                  selected={selectedId === terrace.id}
                />
              </TouchableOpacity>
            </View>
          );
        })}
      </View>

      {/* Loading state while MapLibre boots */}
      {!mapReady && (
        <View style={styles.loadingOverlay} pointerEvents="none">
          <Text style={styles.loadingText}>Chargement de la carte…</Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f5f5f5' },
  markerContainer: { position: 'absolute', width: 36, height: 36 },
  userDotContainer: {
    position: 'absolute',
    width: 24,
    height: 24,
    alignItems: 'center',
    justifyContent: 'center',
  },
  userDot: {
    position: 'absolute',
    width: 14,
    height: 14,
    borderRadius: 7,
    backgroundColor: '#4285F4',
    borderWidth: 2,
    borderColor: '#FFF',
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOpacity: 0.25,
        shadowRadius: 4,
        shadowOffset: { width: 0, height: 1 },
      },
      android: { elevation: 4 },
    }),
  },
  userDotPulse: {
    position: 'absolute',
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: 'rgba(66, 133, 244, 0.25)',
  },
  loadingOverlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
  },
  loadingText: { color: '#666', fontSize: 14, fontWeight: '500' },
});
