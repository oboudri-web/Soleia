/* eslint-disable */
/**
 * Soleia - SunMap (native: WebView + MapLibre + ShadeMap).
 *
 * Architecture inspired by SunSeekr:
 *   - Full-screen WebView hosts MapLibre GL JS + ShadeMap with CARTO Voyager
 *     style and AWS terrarium DEM.
 *   - Markers are NATIVE MapLibre markers (created in the WebView), not RN
 *     overlays. This is dramatically more reliable on iOS (no projection
 *     desync, no layout glitches, gestures fall through naturally).
 *   - The RN component just owns the WebView and forwards 4 things to it:
 *       1) the terrace list                  -> window.updateTerraces(...)
 *       2) the slider time                   -> window.setShadeTime(ts)
 *       3) the focus coords                  -> window.flyTo(...)
 *       4) the selected terrace id           -> window.setSelected(id)
 *     and listens back for marker taps + ShadeMap idle stats + diagnostics.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { View, StyleSheet, Text } from 'react-native';
import { WebView, WebViewMessageEvent } from 'react-native-webview';
import { MAP_HTML } from './mapHtml';
import type { Terrace } from '../api';

type Props = {
  terraces: Terrace[];
  center: { lat: number; lng: number };
  selectedId?: string | null;
  onMarkerPress: (terrace: Terrace) => void;
  userLocation?: { lat: number; lng: number } | null;
  focusCoords?: { lat: number; lng: number } | null;
  forceDark?: boolean; // unused (kept for parent API compat)
  onRegionChange?: (bbox: {
    lat_min: number;
    lat_max: number;
    lng_min: number;
    lng_max: number;
    zoom: number;
  }) => void;
  shadowPolygons?: Array<Array<[number, number]>>; // unused
  enableLegacyShadows?: boolean; // unused
  currentMinutes?: number;
  /** Optional GeoJSON FeatureCollection of terrace polygons. */
  polygonsGeoJSON?: any;
  /** Optional callback fired every ShadeMap idle pass. */
  onShadeIdle?: (stats: { sunny: number; shaded: number; total: number }) => void;
  /** Optional callback when ShadeMap reports a per-terrace sun update. */
  onSunUpdate?: (id: string, sunny: boolean) => void;
  /** Optional callback for live debug overlay (pipeline RN→WebView→Mapbox). */
  onMarkersUpdate?: (info: {
    rnSent?: number;
    webViewReceived?: number;
    markersRendered?: number;
  }) => void;
};

export default function SunMap({
  terraces,
  center,
  selectedId,
  onMarkerPress,
  userLocation,
  focusCoords,
  currentMinutes,
  polygonsGeoJSON,
  onShadeIdle,
  onSunUpdate,
  onMarkersUpdate,
  onRegionChange,
}: Props) {
  const webRef = useRef<WebView>(null);
  const [mapReady, setMapReady] = useState(false);
  const [shadeReady, setShadeReady] = useState(false);
  const lastSentTerracesKeyRef = useRef<string>('');
  const shadeDebounceRef = useRef<any>(null);

  const onMessage = useCallback(
    (ev: WebViewMessageEvent) => {
      try {
        const data = JSON.parse(ev.nativeEvent.data);
        switch (data.type) {
          case 'cssInjected':
            console.log('[soleia.web] css injected (' + data.size + ' bytes)');
            break;
          case 'maplibreInjected':
            console.log(
              '[soleia.web] maplibre injected (' + data.size + ' bytes, hasGlobal=' + data.hasGlobal + ')',
            );
            break;
          case 'shadeMapInjected':
            console.log(
              '[soleia.web] shademap injected (' + data.size + ' bytes, hasGlobal=' + data.hasGlobal + ')',
            );
            break;
          case 'htmlLoaded':
            console.log('[soleia.web] HTML loaded');
            break;
          case 'styleLoaded':
            console.log('[soleia.map] style loaded - ' + data.url);
            break;
          case 'mapReady':
            console.log('[soleia.web] [OK] MapLibre ready');
            setMapReady(true);
            break;
          case 'shadeMapReady':
            console.log('[soleia.shademap] ready - licensed: ' + (data.licensed ? 'true' : 'false'));
            setShadeReady(true);
            break;
          case 'markersAdded':
            console.log(
              '[soleia.markers] ' + data.count + ' markers added at zoom ' + data.zoom,
            );
            break;
          case 'polygonsUpdated':
            console.log('[soleia.polygons] updated count=' + data.count);
            break;
          case 'buildingRoofTranslated':
            console.log(
              '[soleia.map] building-top fill-translate applied: layers=[' +
                (data.layers || []).join(',') + '] sourceUsed=' + (data.sourceUsed || 'native'),
            );
            break;
          case 'shadeIdle':
            console.log(
              '[soleia.shade] idle - updated ' + data.total + ' markers - ' +
                data.sunny + ' sunny / ' + data.shaded + ' shaded',
            );
            if (onShadeIdle) onShadeIdle({ sunny: data.sunny, shaded: data.shaded, total: data.total });
            break;
          case 'sunUpdate':
            if (onSunUpdate) onSunUpdate(data.id, !!data.sunny);
            break;
          case 'markerPress': {
            try {
              const t = terraces.find((x) => x.id === data.id);
              if (t) onMarkerPress(t);
            } catch (errMP) {
              console.warn('[soleia.web] markerPress handler crashed:', errMP);
            }
            break;
          }
          case 'mapError':
            console.warn('[soleia.web] map error:', data.msg);
            break;
          case 'regionChange':
            if (onRegionChange) {
              onRegionChange({
                lat_min: data.lat_min,
                lat_max: data.lat_max,
                lng_min: data.lng_min,
                lng_max: data.lng_max,
                zoom: data.zoom,
              });
            }
            break;
          case 'terracesReceived':
            console.log('[soleia.web] [DBG] WebView received ' + data.count + ' terraces');
            if (onMarkersUpdate) onMarkersUpdate({ webViewReceived: data.count });
            break;
          case 'terracesAck':
            console.log('[soleia.web] [DBG] WebView pushed ' + data.count + ' features to source');
            if (onMarkersUpdate) onMarkersUpdate({ markersRendered: data.count });
            break;
          case 'error':
            console.warn('[soleia.web] error:', data.msg);
            break;
          case 'shadeLog':
            // Verbose - keep silent unless investigating
            break;
          default:
            break;
        }
      } catch (e) {
        // non-JSON message - ignore
      }
    },
    [terraces, onMarkerPress, onShadeIdle, onSunUpdate],
  );

  // Push terraces to the WebView whenever they change AND map is ready
  useEffect(() => {
    if (!mapReady || !webRef.current) return;
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
        type: (t as any).type || 'cafe',
        name: t.name,
      }));
    const key = JSON.stringify(slim.map((t) => t.id + ':' + t.sun_status + ':' + t.type));
    if (key === lastSentTerracesKeyRef.current) return;
    lastSentTerracesKeyRef.current = key;
    const payload = JSON.stringify(slim);
    webRef.current.injectJavaScript(
      'try { window.updateTerraces(' + payload + '); } catch(e){} true;',
    );
    console.log('[soleia.rn] sent ' + slim.length + ' terraces to WebView');
    if (onMarkersUpdate) onMarkersUpdate({ rnSent: slim.length });
  }, [terraces, mapReady]);

  // Push polygons whenever they change
  useEffect(() => {
    if (!mapReady || !webRef.current) return;
    const payload = JSON.stringify(polygonsGeoJSON || { type: 'FeatureCollection', features: [] });
    webRef.current.injectJavaScript(
      'try { window.updatePolygons(' + payload + '); } catch(e){} true;',
    );
  }, [polygonsGeoJSON, mapReady]);

  // Recenter on city change
  useEffect(() => {
    if (!mapReady || !webRef.current) return;
    if (typeof center?.lat !== 'number' || typeof center?.lng !== 'number') return;
    webRef.current.injectJavaScript(
      'try { window.setCenter(' + center.lat + ', ' + center.lng + ', 15); } catch(e){} true;',
    );
  }, [center?.lat, center?.lng, mapReady]);

  // Push user location -> WebView (renders the blue pulsing puck)
  useEffect(() => {
    if (!mapReady || !webRef.current) return;
    if (userLocation && typeof userLocation.lat === 'number' && typeof userLocation.lng === 'number') {
      webRef.current.injectJavaScript(
        'try { window.setUserLocation(' + userLocation.lat + ', ' + userLocation.lng + ', { recenter: true, zoom: 15 }); } catch(e){} true;',
      );
    } else {
      webRef.current.injectJavaScript(
        'try { window.setUserLocation(null); } catch(e){} true;',
      );
    }
  }, [userLocation?.lat, userLocation?.lng, mapReady]);

  // Fly to focus coords on demand
  useEffect(() => {
    if (!mapReady || !webRef.current || !focusCoords) return;
    webRef.current.injectJavaScript(
      'try { window.flyTo(' + focusCoords.lat + ', ' + focusCoords.lng + ', 17); } catch(e){} true;',
    );
  }, [focusCoords?.lat, focusCoords?.lng, mapReady]);

  // Tell WebView which marker is selected
  useEffect(() => {
    if (!mapReady || !webRef.current) return;
    const idStr = selectedId ? JSON.stringify(selectedId) : 'null';
    webRef.current.injectJavaScript(
      'try { window.setSelected(' + idStr + '); } catch(e){} true;',
    );
  }, [selectedId, mapReady]);

  // Bind currentMinutes (slider) -> ShadeMap.setDate (debounced 300ms)
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
        'try { window.setShadeTime(' + ts + '); } catch(e){} true;',
      );
    }, 300);
    return () => {
      if (shadeDebounceRef.current) clearTimeout(shadeDebounceRef.current);
    };
  }, [currentMinutes, shadeReady]);

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
        bounces={false}
        scrollEnabled={false}
        showsHorizontalScrollIndicator={false}
        showsVerticalScrollIndicator={false}
        injectedJavaScriptBeforeContentLoaded={
          'window.__SOLEIA_RN__ = true; window.__SOLEIA_MAPBOX_TOKEN__ = ' +
          JSON.stringify(process.env.EXPO_PUBLIC_MAPBOX_TOKEN || '') +
          '; true;'
        }
        startInLoadingState={false}
        mixedContentMode="always"
        thirdPartyCookiesEnabled
        cacheEnabled
        testID="sun-map-webview"
      />
      {!mapReady && (
        <View style={styles.loadingOverlay} pointerEvents="none">
          <Text style={styles.loadingText}>Chargement de la carte...</Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f6f3ee' },
  loadingOverlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
  },
  loadingText: { color: '#666', fontSize: 14, fontWeight: '500' },
});
