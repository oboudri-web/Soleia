/**
 * SunTerrace - Main Map Screen
 */
import React, { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  FlatList,
  RefreshControl,
  Platform,
  ScrollView,
  Animated,
  Modal,
  Image,
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import Slider from '@react-native-community/slider';
import * as Location from 'expo-location';
import { LinearGradient } from 'expo-linear-gradient';

import { useTheme } from '../src/ThemeContext';
import { useAuth } from '../src/AuthContext';
import { SPACING, FONT_SIZES, RADIUS, TYPE_LABELS, TYPE_ICONS } from '../src/theme';
import { api, type Terrace, type Weather, type SunStatus, type NextSunny } from '../src/api';
import SunMap from '../src/components/SunMap';
import TerraceCard from '../src/components/TerraceCard';
import WeatherBadge from '../src/components/WeatherBadge';
import SoleiaLogo from '../src/components/SoleiaLogo';
import SearchBar from '../src/components/SearchBar';
import SunTimeline from '../src/components/SunTimeline';
import { formatTimeFr } from '../src/utils/time';
import BottomSheet, { BottomSheetFlatList } from '@gorhom/bottom-sheet';
import { requestPushPermissionAndRegister } from '../src/utils/push';
import { getMapThemePref, setMapThemePref, type MapThemePref } from '../src/utils/appState';

const CITY_COORDS: Record<string, { lat: number; lng: number }> = {
  Paris: { lat: 48.8566, lng: 2.3522 },
  Lyon: { lat: 45.764, lng: 4.8357 },
  Marseille: { lat: 43.2965, lng: 5.3698 },
  Bordeaux: { lat: 44.8378, lng: -0.5792 },
  Nantes: { lat: 47.2184, lng: -1.5536 },
  Toulouse: { lat: 43.6047, lng: 1.4442 },
  Nice: { lat: 43.7102, lng: 7.262 },
  Montpellier: { lat: 43.6108, lng: 3.8767 },
};

// ─── Helpers UI header (SunSeekr-style) ────────────────────────────────────────
// WMO weather code → Ionicons name (Open-Meteo standard codes)
function weatherCodeToIcon(code?: number | null): keyof typeof Ionicons.glyphMap {
  if (code == null) return 'partly-sunny-outline';
  if (code === 0) return 'sunny';
  if (code === 1 || code === 2) return 'partly-sunny';
  if (code === 3) return 'cloud';
  if (code === 45 || code === 48) return 'cloudy';
  if (code >= 51 && code <= 67) return 'rainy';
  if (code >= 71 && code <= 77) return 'snow';
  if (code >= 80 && code <= 82) return 'rainy';
  if (code === 95 || code === 96 || code === 99) return 'thunderstorm';
  return 'partly-sunny';
}

const FR_WEEKDAYS_SHORT = ['Dim.', 'Lun.', 'Mar.', 'Mer.', 'Jeu.', 'Ven.', 'Sam.'];
const FR_MONTHS_SHORT = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];

// Formate la date en fonction de l'offset slider (0 = aujourd'hui, 1 = demain, …)
function formatDateOffset(offset: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return `${FR_WEEKDAYS_SHORT[d.getDay()]} ${d.getDate()} ${FR_MONTHS_SHORT[d.getMonth()]}`;
}

// Formate les minutes (depuis 0h) en "12h58" français
function formatMinutesFr(m: number): string {
  const h = Math.floor(m / 60);
  const mm = Math.round(m % 60);
  return `${h}h${String(mm).padStart(2, '0')}`;
}

const TYPE_FILTERS = [
  { id: 'all', label: 'Tous', icon: 'grid' },
  { id: 'bar', label: 'Bar', icon: 'wine' },
  { id: 'cafe', label: 'Café', icon: 'cafe' },
  { id: 'restaurant', label: 'Resto', icon: 'restaurant' },
  { id: 'rooftop', label: 'Rooftop', icon: 'business' },
];

export default function MapScreen() {
  const router = useRouter();
  const { theme, isDark: sysDark } = useTheme();
  const { user: authUser } = useAuth();
  const insets = useSafeAreaInsets();
  const params = useLocalSearchParams<{ city?: string }>();
  const city = (params.city as string) || 'Nantes';

  const [terraces, setTerraces] = useState<Terrace[]>([]);
  const [weather, setWeather] = useState<Weather | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [searchExpanded, setSearchExpanded] = useState(false);
  const [statusFilter, setStatusFilter] = useState<SunStatus | 'all'>('all');
  const [userLocation, setUserLocation] = useState<{ lat: number; lng: number } | null>(null);
  const [mapThemePref, setMapThemePrefState] = useState<MapThemePref>('auto');
  const [tooFarZoomedOut, setTooFarZoomedOut] = useState(false);
  const [nextSunny, setNextSunny] = useState<NextSunny | null>(null);
  const [focusCoords, setFocusCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [sliderExpanded, setSliderExpanded] = useState(false);
  void sliderExpanded; void setSliderExpanded;

  // ── Debug HUD (PR A.1 — markers natifs invisibles) ────────────────────────
  // Affiche un petit badge en haut de l'écran montrant en temps réel
  // combien de features sont envoyées au composant carte natif. Utile pour
  // diagnostiquer si le problème vient du fetch API, du filtre, ou du rendu
  // natif Mapbox. À retirer une fois PR A validée.
  const [mapDebug, setMapDebug] = useState<{ rnSent: number; rendered: number; lastErr?: string }>({
    rnSent: 0,
    rendered: 0,
  });
  const handleMarkersUpdate = useCallback(
    (info: { rnSent?: number; webViewReceived?: number; markersRendered?: number }) => {
      setMapDebug((prev) => ({
        rnSent: info.rnSent ?? prev.rnSent,
        rendered: info.markersRendered ?? prev.rendered,
        lastErr: prev.lastErr,
      }));
    },
    [],
  );

  // @gorhom/bottom-sheet integration — 3 snap points: 10% (handle only), 50% (half), 90% (full)
  const bottomSheetRef = useRef<BottomSheet>(null);
  const snapPoints = useMemo(() => ['10%', '50%', '90%'], []);

  // Ask for push permission 30s after the map has been opened (one-time).
  useEffect(() => {
    if (Platform.OS === 'web') return;
    const timer = setTimeout(() => {
      requestPushPermissionAndRegister(city).catch(() => {});
    }, 30000);
    return () => clearTimeout(timer);
  }, [city]);

  // Load map theme preference from AsyncStorage
  useEffect(() => {
    getMapThemePref().then((p) => setMapThemePrefState(p));
  }, []);

  // Fetch shadow overlay whenever bbox or at_time changes.
  // Cap polygon count to 30 at zoom ≥ 15 to avoid native crashes on Expo Go
  // and preserve performance on dev builds.
  // NOTE: declared AFTER mapBbox/buildAtTime/shadowFetchCtrlRef to avoid TDZ.

  const cycleMapTheme = useCallback(() => {
    const next: MapThemePref =
      mapThemePref === 'auto' ? 'light' : mapThemePref === 'light' ? 'dark' : 'auto';
    setMapThemePrefState(next);
    setMapThemePref(next);
  }, [mapThemePref]);

  // Time slider state : minutes from midnight. Start at now
  const now = new Date();
  const [currentMinutes, setCurrentMinutes] = useState(
    now.getHours() * 60 + now.getMinutes()
  );
  const [isLiveMode, setIsLiveMode] = useState(true);
  // Planning : décalage en jours par rapport à aujourd'hui (0 = aujourd'hui, max 6 = dans 6 jours)
  const [dateOffset, setDateOffset] = useState<number>(0);

  const fadeAnim = useRef(new Animated.Value(0)).current;

  const cityCoords = CITY_COORDS[city] || CITY_COORDS.Nantes;
  const mapCenter = userLocation || cityCoords;

  useEffect(() => {
    (async () => {
      try {
        console.log('[geo] requesting foreground permission...');
        // Vérifier d'abord que le service de localisation est activé sur l'appareil
        try {
          const enabled = await Location.hasServicesEnabledAsync();
          console.log('[geo] location services enabled:', enabled);
          if (!enabled) {
            console.warn('[geo] location services disabled — user must enable in Settings');
            return;
          }
        } catch (eSvc) {
          console.warn('[geo] hasServicesEnabledAsync error', eSvc);
        }

        const { status, canAskAgain } = await Location.requestForegroundPermissionsAsync();
        console.log('[geo] permission status:', status, 'canAskAgain:', canAskAgain);
        if (status !== 'granted') {
          console.warn('[geo] permission denied — user can re-enable from Settings → Soleia');
          return;
        }

        console.log('[geo] fetching current position (Balanced accuracy, 8s timeout)...');
        const pos = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.Balanced,
        });
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        console.log(`[geo] ✅ position received: lat=${lat.toFixed(5)} lng=${lng.toFixed(5)} (accuracy=${pos.coords.accuracy}m)`);
        setUserLocation({ lat, lng });
        // Centrer la carte explicitement (en plus du recenter dans setUserLocation côté WebView).
        // Ceci utilise focusCoords qui déclenche window.flyTo dans le WebView via SunMap.
        setFocusCoords({ lat, lng });

        // Auto-détection de la ville la plus proche (parmi les villes supportées).
        // On bascule uniquement si la ville détectée est différente de celle affichée.
        try {
          const toRad = (deg: number) => (deg * Math.PI) / 180;
          const haversine = (a: any, b: any) => {
            const R = 6371;
            const dLat = toRad(b.lat - a.lat);
            const dLng = toRad(b.lng - a.lng);
            const x =
              Math.sin(dLat / 2) ** 2 +
              Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
            return 2 * R * Math.asin(Math.sqrt(x));
          };
          let bestName = city;
          let bestDist = Infinity;
          Object.entries(CITY_COORDS).forEach(([name, coords]) => {
            const d = haversine({ lat, lng }, coords);
            if (d < bestDist) {
              bestDist = d;
              bestName = name;
            }
          });
          // Seuil 50 km : si l'utilisateur est à plus de 50km de toutes les villes,
          // on garde la ville par défaut (URL/Nantes).
          if (bestName !== city && bestDist <= 50) {
            console.log(`[geo] auto-detected nearest city: ${bestName} (${bestDist.toFixed(1)} km) → switching from ${city}`);
            router.replace({ pathname: '/map', params: { city: bestName } });
          } else {
            console.log(`[geo] keeping city=${city} (nearest=${bestName} @ ${bestDist.toFixed(1)} km)`);
          }
        } catch (eAuto) {
          console.warn('[geo] auto-city detection error', eAuto);
        }
      } catch (e) {
        console.warn('[geo] ❌ error', e);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const centerOnUser = async () => {
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== 'granted') return;
      const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      setUserLocation({ lat: pos.coords.latitude, lng: pos.coords.longitude });
    } catch (e) {
      console.warn('Location error', e);
    }
  };

  // Construit une Date correspondant au dateOffset+heure sélectionnée
  const buildSelectedDate = useCallback(() => {
    const d = new Date();
    d.setDate(d.getDate() + dateOffset);
    const h = Math.floor(currentMinutes / 60);
    const m = currentMinutes % 60;
    d.setHours(h, m, 0, 0);
    return d;
  }, [currentMinutes, dateOffset]);

  const buildAtTime = useCallback(() => {
    const d = buildSelectedDate();
    const pad = (n: number) => n.toString().padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`;
  }, [buildSelectedDate]);

  // Label court pour la clock pill : "Maintenant" | "14h30" | "Sam 14h"
  const WEEKDAY_SHORT = ['Dim', 'Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam'];
  const clockPillLabel = useMemo(() => {
    if (isLiveMode && dateOffset === 0) return 'Maintenant';
    const h = Math.floor(currentMinutes / 60);
    const m = currentMinutes % 60;
    const hStr = m === 0 ? `${h}h` : `${h}h${m.toString().padStart(2, '0')}`;
    if (dateOffset === 0) return hStr;
    if (dateOffset === 1) return `Demain ${hStr}`;
    const d = buildSelectedDate();
    return `${WEEKDAY_SHORT[d.getDay()]} ${hStr}`;
  }, [isLiveMode, dateOffset, currentMinutes, buildSelectedDate]);

  // Onglets des 7 prochains jours [Aujourd'hui, Demain, Mer, Jeu, Ven, Sam, Dim]
  const dateTabs = useMemo(() => {
    const tabs: { offset: number; label: string; dayNum: number }[] = [];
    for (let i = 0; i < 7; i++) {
      const d = new Date();
      d.setDate(d.getDate() + i);
      let label: string;
      if (i === 0) label = "Aujourd'hui";
      else if (i === 1) label = 'Demain';
      else label = WEEKDAY_SHORT[d.getDay()];
      tabs.push({ offset: i, label, dayNum: d.getDate() });
    }
    return tabs;
  }, []);

  // Plage "jour" approximative pour la timeline inline (sunrise/sunset
  // varient selon le mois en France métropolitaine ~45°N). Remplacement
  // simple d'un vrai calcul astro tant qu'on n'a pas l'info sunrise/sunset
  // côté backend. La SunTimeline s'en sert pour peindre la bande jaune.
  const inlineSunnyRanges = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() + dateOffset);
    const month = d.getMonth(); // 0-11
    // Approximation saisonnière (France ~46°N) — hh:mm
    const WINDOWS: Array<[string, string]> = [
      ['08:00', '17:30'], // Jan
      ['08:00', '18:00'], // Feb
      ['07:30', '19:00'], // Mar
      ['07:00', '20:30'], // Apr
      ['06:30', '21:30'], // May
      ['06:00', '22:00'], // Jun
      ['06:00', '22:00'], // Jul
      ['06:30', '21:30'], // Aug
      ['07:00', '20:30'], // Sep
      ['07:30', '19:00'], // Oct
      ['08:00', '17:30'], // Nov
      ['08:30', '17:00'], // Dec
    ];
    const [start, end] = WINDOWS[month];
    return [{ start, end }];
  }, [dateOffset]);


  // Bounding box visible sur la carte (pour charger uniquement les terrasses visibles)
  // Stratégie : on élargit de 50% pour créer un buffer, et on ne refetch que si la
  // nouvelle région visible SORT du bbox déjà chargé. Évite les refetch en spam quand
  // l'utilisateur panne/zoom légèrement.
  const [mapBbox, setMapBbox] = useState<{
    lat_min: number;
    lat_max: number;
    lng_min: number;
    lng_max: number;
  } | null>(null);
  const fetchedBboxRef = useRef<{
    lat_min: number;
    lat_max: number;
    lng_min: number;
    lng_max: number;
  } | null>(null);
  const bboxDebounceRef = useRef<any>(null);

  // ── Initialisation du bbox dès qu'on a une position (user ou ville par défaut)
  // pour que la 1ère requête API soit déjà géo-localisée et ne rapatrie pas
  // 200 terrasses éparpillées dans toute la France.
  // On re-init quand userLocation arrive (basculement Nantes→Paris) tant que
  // l'utilisateur n'a pas encore pan/zoomé manuellement (cf. fetchedBboxRef).
  useEffect(() => {
    const ref = userLocation || cityCoords;
    if (!ref || typeof ref.lat !== 'number' || typeof ref.lng !== 'number') return;
    // Si l'utilisateur a déjà manipulé la carte (fetchedBboxRef set par onRegionChange),
    // on ne touche plus au bbox automatiquement.
    if (fetchedBboxRef.current) return;
    const DELTA = 0.05; // ~5.5 km côté Nord/Sud, ~3.5 km côté Est/Ouest à 47° lat
    const initial = {
      lat_min: ref.lat - DELTA,
      lat_max: ref.lat + DELTA,
      lng_min: ref.lng - DELTA,
      lng_max: ref.lng + DELTA,
    };
    setMapBbox(initial);
    console.log(
      `[map.bbox] ⚡ initial bbox set around ${userLocation ? 'userLocation' : city} (${ref.lat.toFixed(4)}, ${ref.lng.toFixed(4)})`,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userLocation?.lat, userLocation?.lng, cityCoords.lat, cityCoords.lng]);

  // Shadow overlay polygons (fetched from /api/shadows)
  const [shadowPolygons, setShadowPolygons] = useState<Array<Array<[number, number]>>>([]);
  // Flag pour ré-fetch les ombres OSM legacy (désactivé : ShadeMap dans la
  // WebView remplace tout le shadow engine backend).
  const ENABLE_LEGACY_SHADOWS = false;
  const shadowFetchCtrlRef = useRef<AbortController | null>(null);

  // Fetch shadow overlay whenever bbox or at_time changes.
  // Cap polygon count to 30 at zoom ≥ 15 to avoid native crashes on Expo Go
  // and preserve performance on dev builds.
  useEffect(() => {
    if (!ENABLE_LEGACY_SHADOWS) {
      // Mapbox Standard v12 directional light s'occupe maintenant des ombres
      // GPU sur les bâtiments 3D — pas besoin de fetch /api/shadows.
      setShadowPolygons([]);
      return;
    }
    if (!mapBbox) {
      console.log('[shadows] skip: no mapBbox yet');
      setShadowPolygons([]);
      return;
    }
    const spanLat = mapBbox.lat_max - mapBbox.lat_min;
    const spanLng = mapBbox.lng_max - mapBbox.lng_min;
    // Seuil large : les ombres doivent être visibles dès le niveau quartier
    // sans zoom extrême. 0.08° ≈ 9 km côté — aligné avec MAX_SPAN backend.
    const maxSpan = 0.08;
    if (spanLat > maxSpan || spanLng > maxSpan) {
      console.log(
        `[shadows] skip: zoom too low — spanLat=${spanLat.toFixed(4)} spanLng=${spanLng.toFixed(4)} (max=${maxSpan}) → zoomer pour voir les ombres`,
      );
      setShadowPolygons([]);
      return;
    }
    if (shadowFetchCtrlRef.current) {
      try { shadowFetchCtrlRef.current.abort(); } catch {}
    }
    const ctrl = new AbortController();
    shadowFetchCtrlRef.current = ctrl;

    const isPlanningMode = dateOffset > 0 || !isLiveMode;
    const atTime = isPlanningMode ? buildAtTime() : undefined;

    const t0 = Date.now();
    console.log(
      `[shadows] FETCH — bbox ${mapBbox.lat_min.toFixed(4)},${mapBbox.lng_min.toFixed(4)} → ${mapBbox.lat_max.toFixed(4)},${mapBbox.lng_max.toFixed(4)} | at_time=${atTime || 'now'}`,
    );
    (async () => {
      try {
        const res = await api.getShadowOverlay({
          lat_min: mapBbox.lat_min,
          lat_max: mapBbox.lat_max,
          lng_min: mapBbox.lng_min,
          lng_max: mapBbox.lng_max,
          at_time: atTime,
        });
        const dt = Date.now() - t0;
        if (!ctrl.signal.aborted) {
          const rawCount = (res.polygons || []).length;
          // Cap réduit à 50 pour stabilité iOS — au-dessus, ShapeSource +
          // FillLayer Mapbox peuvent crasher sur zoom/dézoom rapides.
          const capped = (res.polygons || []).slice(0, 50);
          console.log(
            `[shadows] OK ${dt}ms — backend returned ${rawCount} polys (${res.building_count || 0} buildings, sun el=${res.sun?.el?.toFixed?.(1) || '??'}°) → kept ${capped.length} | cached=${res.cached || false} | reason=${res.reason || 'none'}`,
          );
          if (capped.length > 0) {
            console.log(
              `[shadows] first poly has ${capped[0].length} points, sample=${JSON.stringify(capped[0][0])}`,
            );
          }
          setShadowPolygons(capped);
        }
      } catch (e: any) {
        if (!ctrl.signal.aborted) {
          console.warn('[shadows] FETCH FAILED:', e?.message || e);
          setShadowPolygons([]);
        }
      }
    })();
  }, [mapBbox, isLiveMode, dateOffset, buildAtTime, currentMinutes]);

  const onMapRegionChange = useCallback(
    (bbox: { lat_min: number; lat_max: number; lng_min: number; lng_max: number; zoom: number }) => {
      if (bboxDebounceRef.current) clearTimeout(bboxDebounceRef.current);
      bboxDebounceRef.current = setTimeout(() => {
        const visibleLatSpan = bbox.lat_max - bbox.lat_min;
        const visibleLngSpan = bbox.lng_max - bbox.lng_min;

        // Si la zone visible est TOUJOURS dans le bbox déjà fetché, on ne refetch pas.
        // Le user peut zoomer/paner dans la zone sans provoquer de requête.
        const fetched = fetchedBboxRef.current;
        if (
          fetched &&
          bbox.lat_min >= fetched.lat_min &&
          bbox.lat_max <= fetched.lat_max &&
          bbox.lng_min >= fetched.lng_min &&
          bbox.lng_max <= fetched.lng_max
        ) {
          return; // pas de refetch
        }

        // Élargir le bbox de 50% pour créer un buffer de préchargement
        const buffered = {
          lat_min: bbox.lat_min - visibleLatSpan * 0.25,
          lat_max: bbox.lat_max + visibleLatSpan * 0.25,
          lng_min: bbox.lng_min - visibleLngSpan * 0.25,
          lng_max: bbox.lng_max + visibleLngSpan * 0.25,
        };
        fetchedBboxRef.current = buffered;
        setMapBbox(buffered);
      }, 600);
    },
    [],
  );

  const loadData = useCallback(async () => {
    try {
      // En mode live OU aujourd'hui sans planning → pas d'at_time ; sinon on envoie la date+heure
      const isPlanningMode = dateOffset > 0 || !isLiveMode;
      const atTime = isPlanningMode ? buildAtTime() : undefined;

      // ── Pagination bbox stricte : on N'EXIGE PAS de bbox au tout 1er render
      // (le moveend du Mapbox arrivera dans <600ms après le mapReady), mais
      // dès qu'on en a un, on ne charge que dans cette zone et max 200.
      // Si le bbox est trop large (zoom dezoomé France entière), on skip.

      // Skip si pas encore de bbox initial (sera relancé dès que `mapBbox`
      // est settled par le useEffect "[map.bbox] initial bbox set" ou par
      // le moveend de la WebView). Évite une 1ère requête globale inutile.
      if (!mapBbox) {
        console.log('[map.loadData] ⏸  skipped — waiting for initial bbox');
        return;
      }
      const MAX_BBOX_SPAN_DEG = 0.5; // ≈55 km côté max — sinon "Zoomez"
      let tooFar = false;
      const spanLat = mapBbox.lat_max - mapBbox.lat_min;
      const spanLng = mapBbox.lng_max - mapBbox.lng_min;
      if (spanLat > MAX_BBOX_SPAN_DEG || spanLng > MAX_BBOX_SPAN_DEG) {
        tooFar = true;
        console.log(`[map.loadData] ⚠️  bbox too wide (spanLat=${spanLat.toFixed(3)}, spanLng=${spanLng.toFixed(3)}) → user must zoom in`);
      }
      setTooFarZoomedOut(tooFar);
      if (tooFar) {
        setTerraces([]);
        setLoading(false);
        setRefreshing(false);
        return;
      }

      // Bug 7: bigger default limit (500 instead of 200) so dense city zones
      // don't get clipped. When the user has zoomed in close (spanLat < 0.012°,
      // ~zoom level 15+ on a phone), drop the limit entirely so every terrace
      // in the visible viewport is rendered.
      const isCloseZoom = spanLat < 0.012;
      const params: any = { limit: isCloseZoom ? 5000 : 500 };
      if (typeFilter !== 'all') params.type = typeFilter;
      if (atTime) params.at_time = atTime;
      if (mapBbox) {
        params.lat_min = mapBbox.lat_min;
        params.lat_max = mapBbox.lat_max;
        params.lng_min = mapBbox.lng_min;
        params.lng_max = mapBbox.lng_max;
      }

      // Construire l'URL de debug (relative — c'est uniquement pour le console.log,
      // l'appel réel passe par api.listTerraces qui utilise EXPO_PUBLIC_BACKEND_URL).
      const dbgUrl =
        '/api/terraces?' +
        Object.entries(params)
          .map(([k, v]) => `${k}=${typeof v === 'number' ? v.toFixed(4) : v}`)
          .join('&');
      console.log('[map.loadData] 📡 calling: ' + dbgUrl);

      const [terracesRes, weatherRes] = await Promise.all([
        api.listTerraces(params),
        api.getWeather(city).catch(() => null),
      ]);
      console.log(
        `[map.loadData] ✅ ${terracesRes.terraces.length} terraces loaded — bbox=${mapBbox ? 'yes' : 'no'} at_time=${atTime || 'now'}`,
      );
      // ── Stats globales + breakdown par ville
      try {
        const all = terracesRes.terraces;
        const sunny = all.filter((t) => t.sun_status === 'sunny').length;
        const soon = all.filter((t) => t.sun_status === 'soon').length;
        const shade = all.filter((t) => t.sun_status === 'shade').length;
        console.log(
          `[stats] BBOX: ${all.length} terraces | sunny=${sunny} | soon=${soon} | shade=${shade}`,
        );
      } catch (_e) {}
      setTerraces(terracesRes.terraces);
      setWeather(weatherRes);

      Animated.timing(fadeAnim, {
        toValue: 1,
        duration: 400,
        useNativeDriver: true,
      }).start();
    } catch (e) {
      console.warn('Failed to load data', e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [city, typeFilter, isLiveMode, dateOffset, buildAtTime, mapBbox, fadeAnim]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Auto-refresh every 5 minutes in live mode
  useEffect(() => {
    if (!isLiveMode) return;
    const interval = setInterval(() => {
      const n = new Date();
      setCurrentMinutes(n.getHours() * 60 + n.getMinutes());
    }, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [isLiveMode]);

  const filteredTerraces = useMemo(() => {
    // 1) Filter by status
    const base = statusFilter === 'all'
      ? terraces
      : terraces.filter((t) => t.sun_status === statusFilter);
    if (!base.length) return base;

    // 2) Haversine distance (km)
    const toRad = (deg: number) => (deg * Math.PI) / 180;
    const haversine = (lat1: number, lng1: number, lat2: number, lng2: number) => {
      const R = 6371;
      const dLat = toRad(lat2 - lat1);
      const dLng = toRad(lng2 - lng1);
      const a =
        Math.sin(dLat / 2) ** 2 +
        Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
      return 2 * R * Math.asin(Math.sqrt(a));
    };

    // 3) 4-tier sort (Near+Sun > Near+Soon > Near+Shade > Far)
    const NEAR_KM = 1.0;
    const ref = userLocation || mapCenter;
    const decorated = base.map((t) => {
      const dist =
        ref && typeof ref.lat === 'number' && typeof ref.lng === 'number'
          ? haversine(ref.lat, ref.lng, t.lat, t.lng)
          : t.distance_km != null
          ? t.distance_km
          : 999;
      const isNear = dist <= NEAR_KM;
      let tier = 4; // far
      if (isNear) {
        if (t.sun_status === 'sunny') tier = 1;
        else if (t.sun_status === 'soon') tier = 2;
        else tier = 3; // shade
      }
      return { t, dist, tier };
    });
    decorated.sort((a, b) => {
      if (a.tier !== b.tier) return a.tier - b.tier;
      return a.dist - b.dist;
    });
    return decorated.map((d) => d.t);
  }, [terraces, statusFilter, userLocation?.lat, userLocation?.lng, mapCenter.lat, mapCenter.lng]);

  const sunnyCount = useMemo(
    () => terraces.filter((t) => t.sun_status === 'sunny').length,
    [terraces]
  );

  // Mode nocturne : heure actuelle hors 7h-21h OU 0 terrasse au soleil en live (désactivé en planning)
  const isNightMode = useMemo(() => {
    if (!isLiveMode || dateOffset > 0) return false;
    const h = Math.floor(currentMinutes / 60);
    const afterHours = h >= 21 || h < 7;
    return afterHours || (terraces.length > 0 && sunnyCount === 0);
  }, [isLiveMode, dateOffset, currentMinutes, terraces.length, sunnyCount]);

  // Compute final dark map : user override > auto (system dark OR night mode)
  const mapIsDark = useMemo(() => {
    if (mapThemePref === 'dark') return true;
    if (mapThemePref === 'light') return false;
    return sysDark || isNightMode;
  }, [mapThemePref, sysDark, isNightMode]);

  // Charger la prochaine terrasse au soleil quand on passe en mode nuit
  useEffect(() => {
    let cancelled = false;
    if (!isNightMode) {
      setNextSunny(null);
      return;
    }
    (async () => {
      try {
        const data = await api.getNextSunny(city);
        if (!cancelled) setNextSunny(data);
      } catch (e) {
        console.warn('next-sunny error', e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isNightMode, city]);

  const formatTime = (mins: number) => formatTimeFr(mins);

  const onMarkerPress = (t: Terrace) => {
    try {
      setSelectedId(t.id);
      // Ouvre directement la fiche terrasse au tap (cluster individual point)
      const isPlanning = dateOffset > 0 || !isLiveMode;
      router.push({
        pathname: '/terrace/[id]',
        params: { id: t.id, at_time: isPlanning ? buildAtTime() : '' },
      });
    } catch (e) {
      console.warn('[onMarkerPress] error opening terrace:', e);
    }
  };

  const onCardPress = (t: Terrace) => {
    const isPlanning = dateOffset > 0 || !isLiveMode;
    router.push({ pathname: '/terrace/[id]', params: { id: t.id, at_time: isPlanning ? buildAtTime() : '' } });
  };

  const setLiveNow = () => {
    const n = new Date();
    setCurrentMinutes(n.getHours() * 60 + n.getMinutes());
    setIsLiveMode(true);
    setDateOffset(0);
  };

  return (
    <View style={[styles.container, { backgroundColor: theme.background }]}>
      {/* Map */}
      <View style={styles.mapContainer}>
        <SunMap
          terraces={filteredTerraces}
          center={mapCenter}
          selectedId={selectedId}
          onMarkerPress={onMarkerPress}
          userLocation={userLocation}
          focusCoords={focusCoords}
          forceDark={mapIsDark}
          onRegionChange={onMapRegionChange}
          onMarkersUpdate={handleMarkersUpdate}
          shadowPolygons={shadowPolygons}
          enableLegacyShadows={ENABLE_LEGACY_SHADOWS}
          currentMinutes={currentMinutes}
        />
      </View>

      {/* ── DEBUG HUD (PR A.1) — markers natifs invisibles ───────────────────
          Petit badge en haut-gauche (sous safe area) montrant en live la
          chaîne de données : terraces fetched → filtrées → envoyées au natif.
          Si rnSent>0 mais rien ne s'affiche → le bug est dans CircleLayer.
          Si rnSent=0 → le bug est dans loadData() / filteredTerraces.
          À retirer une fois PR A validée par l'utilisateur. */}
      <SafeAreaView
        edges={['top']}
        pointerEvents="none"
        style={styles.debugHudWrap}
      >
        <View style={styles.debugHud}>
          <Text style={styles.debugHudText}>
            🐛 fetched={terraces.length} · filtered={filteredTerraces.length} · rnSent={mapDebug.rnSent} · rendered={mapDebug.rendered}
          </Text>
          {mapBbox ? (
            <Text style={styles.debugHudTextSmall}>
              bbox=[{mapBbox.lat_min.toFixed(3)},{mapBbox.lng_min.toFixed(3)} → {mapBbox.lat_max.toFixed(3)},{mapBbox.lng_max.toFixed(3)}]
            </Text>
          ) : (
            <Text style={styles.debugHudTextSmall}>bbox=null (waiting…)</Text>
          )}
        </View>
      </SafeAreaView>

      {/* Top overlay: SunSeekr-style compact header + slider+search row + filter pills */}
      <SafeAreaView style={styles.topOverlay} edges={['top']} pointerEvents="box-none">
        {/* Compact header — 3 colonnes inline (logo+brand | ville+météo | date) */}
        <View style={styles.compactHeader}>
          {/* Gauche : icône app + Soleia */}
          <TouchableOpacity
            testID="btn-profile"
            activeOpacity={0.7}
            onPress={() => router.push('/profile')}
            style={styles.headerLeft}
            hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
          >
            <Image
              source={require('../assets/images/icon.png')}
              style={styles.headerLogo}
              resizeMode="contain"
            />
            <Text style={[styles.headerBrand, { color: theme.text }]}>Soleia</Text>
          </TouchableOpacity>

          {/* Centre : ville détectée (non-cliquable) + icône météo dynamique + température */}
          <View
            testID="city-display"
            style={styles.headerCenter}
          >
            <Text style={[styles.headerCity, { color: theme.text }]} numberOfLines={1}>
              {city}
            </Text>
            <Ionicons
              name={weatherCodeToIcon(weather?.weather_code)}
              size={16}
              color={theme.primary}
              style={{ marginLeft: 4 }}
            />
            <Text style={[styles.headerTemp, { color: theme.text }]}>
              {weather?.temperature != null ? `${Math.round(weather.temperature)}°` : '—°'}
            </Text>
          </View>

          {/* Droite : jour/date — reflète l'offset du slider */}
          <Text style={[styles.headerDate, { color: theme.textSecondary }]}>
            {formatDateOffset(dateOffset)}
          </Text>
        </View>

        {/* Slider row : barre orange + heure courante + bouton loupe */}
        <View style={styles.sliderRow}>
          <View style={styles.sliderRowSliderWrap}>
            <Slider
              testID="time-slider"
              style={styles.minimalSlider}
              minimumValue={6 * 60}
              maximumValue={22 * 60}
              step={15}
              value={currentMinutes}
              onValueChange={(v) => {
                setCurrentMinutes(v);
                setIsLiveMode(false);
              }}
              minimumTrackTintColor={theme.primary}
              maximumTrackTintColor={mapIsDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.15)'}
              thumbTintColor={theme.primary}
            />
            <View style={styles.sliderTicksRow} pointerEvents="none">
              <Text style={[styles.sliderTick, { left: '12.5%', color: theme.textTertiary }]}>8h</Text>
              <Text style={[styles.sliderTick, { left: '37.5%', color: theme.textTertiary }]}>12h</Text>
              <Text style={[styles.sliderTick, { left: '75%', color: theme.textTertiary }]}>18h</Text>
            </View>
          </View>
          <Text style={[styles.sliderTimeLabel, { color: theme.text }]}>
            {formatMinutesFr(currentMinutes)}
          </Text>
          <TouchableOpacity
            testID="btn-search-toggle"
            activeOpacity={0.85}
            onPress={() => setSearchExpanded((v) => !v)}
            style={[styles.searchBtn, { backgroundColor: theme.surface, borderColor: theme.border }]}
            hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
          >
            <Ionicons name={searchExpanded ? 'close' : 'search'} size={16} color={theme.primary} />
          </TouchableOpacity>
        </View>

        {/* Search bar (collapsible) */}
        {searchExpanded && (
          <View style={styles.searchBarSlot}>
            <SearchBar
              city={city}
              onSelect={(t) => {
                setSelectedId(t.id);
                setFocusCoords({ lat: t.lat, lng: t.lng });
                setSearchExpanded(false);
                const isPlanning = dateOffset > 0 || !isLiveMode;
                setTimeout(() => {
                  router.push({
                    pathname: '/terrace/[id]',
                    params: { id: t.id, at_time: isPlanning ? buildAtTime() : '' },
                  });
                }, 300);
              }}
            />
          </View>
        )}

        {/* Type filters — discreet pills */}
        <View style={styles.typePillsRow} pointerEvents="box-none">
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.typePillsContent}
          >
            {TYPE_FILTERS.map((f) => {
              const active = typeFilter === f.id;
              return (
                <TouchableOpacity
                  key={f.id}
                  testID={`top-filter-type-${f.id}`}
                  activeOpacity={0.85}
                  onPress={() => setTypeFilter(f.id)}
                  style={[
                    styles.typePill,
                    {
                      backgroundColor: active ? theme.primary : theme.surface,
                      borderColor: active ? theme.primary : theme.border,
                    },
                  ]}
                >
                  <Text
                    style={[
                      styles.typePillText,
                      {
                        color: active ? '#FFFFFF' : theme.text,
                        fontWeight: active ? '700' : '500',
                      },
                    ]}
                  >
                    {f.label}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </ScrollView>
        </View>
      </SafeAreaView>

      {/* Bottom sheet: list of terraces (@gorhom/bottom-sheet, 3 snap points) */}
      <BottomSheet
        ref={bottomSheetRef}
        index={0}
        snapPoints={snapPoints}
        enablePanDownToClose={false}
        backgroundStyle={{ backgroundColor: theme.surface }}
        handleIndicatorStyle={{ backgroundColor: theme.border, width: 48, height: 5 }}
        topInset={0}
      >

        {/* Filters row */}
        <View style={styles.filtersWrap}>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.filtersContent}
          >
            {/* Status filters */}
            {[
              { id: 'all', label: 'Tous' },
              { id: 'sunny', label: 'Au soleil' },
              { id: 'soon', label: 'Bientôt' },
              { id: 'shade', label: 'Ombre' },
            ].map((f) => {
              const active = statusFilter === f.id;
              return (
                <TouchableOpacity
                  key={f.id}
                  testID={`filter-status-${f.id}`}
                  activeOpacity={0.8}
                  onPress={() => setStatusFilter(f.id as any)}
                  style={[
                    styles.filterChip,
                    {
                      backgroundColor: active ? theme.primary : theme.surfaceSecondary,
                    },
                  ]}
                >
                  <Text
                    style={[
                      styles.filterText,
                      {
                        color: active ? '#FFFFFF' : theme.textSecondary,
                        fontWeight: active ? '600' : '400',
                      },
                    ]}
                  >
                    {f.label}
                  </Text>
                </TouchableOpacity>
              );
            })}

          </ScrollView>
        </View>

        {/* Terrace list */}
        {loading ? (
          <View style={styles.loadingContainer}>
            <ActivityIndicator color={theme.primary} size="large" />
            <Text style={[styles.loadingText, { color: theme.textSecondary }]}>
              Calcul de l'ensoleillement...
            </Text>
          </View>
        ) : (
          <BottomSheetFlatList
            testID="terrace-list"
            data={filteredTerraces}
            keyExtractor={(item: Terrace) => item.id}
            contentContainerStyle={[styles.listContent, { paddingBottom: insets.bottom + SPACING.xl }]}
            showsVerticalScrollIndicator={false}
            refreshControl={
              <RefreshControl
                refreshing={refreshing}
                onRefresh={() => {
                  setRefreshing(true);
                  loadData();
                }}
                tintColor={theme.primary}
              />
            }
            ListHeaderComponent={
              <>
                {isNightMode && nextSunny?.found && (
                  <View testID="night-card" style={styles.nightCard}>
                    <View style={styles.nightCardIcon}>
                      <Ionicons name="moon" size={18} color="#555555" />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.nightCardTitle}>
                        {nextSunny.is_tomorrow ? 'Pas de soleil ce soir' : 'Plus de soleil pour le moment'}
                      </Text>
                      <Text style={styles.nightCardSubtitle}>
                        Prochaine terrasse ensoleillée{' '}
                        <Text style={styles.nightCardStrong}>
                          {nextSunny.is_tomorrow ? 'demain' : "aujourd'hui"} à {nextSunny.first_sunny_time}
                          {nextSunny.terrace_name ? ` · ${nextSunny.terrace_name}` : ''}
                        </Text>
                      </Text>
                    </View>
                  </View>
                )}
                <View style={styles.listHeader}>
                  <Text style={[styles.listTitle, { color: theme.text }]}>
                    {filteredTerraces.length} terrasse{filteredTerraces.length > 1 ? 's' : ''}
                  </Text>
                  <Text style={[styles.listSubtitle, { color: theme.textSecondary }]}>
                    {dateOffset > 0
                      ? `le ${clockPillLabel.toLowerCase()}`
                      : isLiveMode
                      ? 'en temps réel'
                      : `à ${formatTime(currentMinutes)}`}
                  </Text>
                </View>
              </>
            }
            ListEmptyComponent={
              tooFarZoomedOut ? (
                <View style={styles.emptyState}>
                  <Ionicons name="search" size={40} color={theme.primary} />
                  <Text style={[styles.emptyText, { color: theme.text, fontWeight: '600' }]}>
                    Zoomez pour voir les terrasses
                  </Text>
                  <Text style={[styles.emptyText, { color: theme.textSecondary, marginTop: 4 }]}>
                    Pincez la carte pour explorer une zone plus précise
                  </Text>
                </View>
              ) : (
                <View style={styles.emptyState}>
                  <Ionicons name="sad-outline" size={40} color={theme.textTertiary} />
                  <Text style={[styles.emptyText, { color: theme.textSecondary }]}>
                    Aucune terrasse trouvée avec ces filtres
                  </Text>
                </View>
              )
            }
            renderItem={({ item }: { item: Terrace }) => (
              <TerraceCard terrace={item} onPress={() => onCardPress(item)} />
            )}
          />
        )}
      </BottomSheet>

    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  mapContainer: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
  },
  topOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
  },
  // ── Debug HUD (PR A.1 — markers natifs) ──────────────────────────────────
  debugHudWrap: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    alignItems: 'center',
    zIndex: 9999,
    elevation: 9999,
  },
  debugHud: {
    backgroundColor: 'rgba(0,0,0,0.78)',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
    marginTop: 4,
    maxWidth: '94%',
  },
  debugHudText: {
    color: '#FFFFFF',
    fontSize: 11,
    fontWeight: '600',
    textAlign: 'center',
  },
  debugHudTextSmall: {
    color: '#A0A0A0',
    fontSize: 9,
    textAlign: 'center',
    marginTop: 2,
  },
  topRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',    paddingTop: SPACING.sm,
    paddingHorizontal: SPACING.md,
  },
  // Minimal header (SunSeekr-style) : city left, profile right — no logo, no weather, no search.
  minimalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: SPACING.md,
    paddingTop: SPACING.sm,
    paddingBottom: 2,
  },
  // ─── New compact header (SunSeekr-style: 3 columns inline) ───
  compactHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: SPACING.md,
    paddingTop: SPACING.sm,
    paddingBottom: 4,
    gap: 8,
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    flexShrink: 1,
  },
  headerLogo: {
    width: 28,
    height: 28,
    borderRadius: 6,
  },
  headerBrand: {
    fontSize: 15,
    fontWeight: '800',
    letterSpacing: -0.3,
  },
  headerCenter: {
    flexDirection: 'row',
    alignItems: 'center',
    flexShrink: 1,
    gap: 4,
  },
  headerCity: {
    fontSize: 14,
    fontWeight: '700',
    letterSpacing: -0.2,
    maxWidth: 90,
  },
  headerTemp: {
    fontSize: 13,
    fontWeight: '600',
    marginLeft: 2,
  },
  headerDate: {
    fontSize: 12,
    fontWeight: '600',
    flexShrink: 0,
  },
  // ─── Slider row (slider + time + search) ───
  sliderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: SPACING.md,
    marginTop: 2,
    marginBottom: 4,
    gap: 8,
  },
  sliderRowSliderWrap: {
    flex: 1,
    minHeight: 40,
  },
  sliderTimeLabel: {
    fontSize: 13,
    fontWeight: '700',
    letterSpacing: -0.2,
    minWidth: 48,
    textAlign: 'right',
  },
  searchBtn: {
    width: 30,
    height: 30,
    borderRadius: 15,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  searchBarSlot: {
    paddingHorizontal: SPACING.md,
    marginTop: 4,
  },
  cityTextBtn: {
    paddingVertical: 4,
  },
  cityTextMinimal: {
    fontSize: 20,
    fontWeight: '700',
    letterSpacing: -0.4,
  },
  cityCaret: {
    fontSize: 13,
    fontWeight: '400',
  },
  profileBtnMinimal: {
    width: 36,
    height: 36,
    borderRadius: 18,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  minimalSliderSlot: {
    paddingHorizontal: SPACING.md,
    marginTop: 2,
    marginBottom: 4,
  },
  minimalSlider: {
    width: '100%',
    height: 28,
  },
  sliderTicksRow: {
    position: 'relative',
    height: 14,
    marginTop: -4,
  },
  sliderTick: {
    position: 'absolute',
    fontSize: 10,
    fontWeight: '500',
    transform: [{ translateX: -6 }],
  },
  topRowHeader: {
    position: 'relative',
    paddingHorizontal: SPACING.md,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingTop: SPACING.sm,
    height: 54,
  },
  topRowCenterAbs: {
    position: 'absolute',
    left: 0,
    right: 0,
    top: 0,
    bottom: 0,
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1,
  },
  topRowSideLeft: {
    zIndex: 2,
  },
  topRowSideRight: {
    zIndex: 2,
  },
  topRowLeft: {
    flex: 1,
    alignItems: 'flex-start',
  },
  topRowCenter: {
    flex: 1,
    alignItems: 'center',
  },
  topRowRight: {
    flex: 1,
    alignItems: 'flex-end',
  },
  searchIconBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.10,
    shadowRadius: 10,
    elevation: 4,
  },
  logoChip: {
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.sm,
    borderRadius: RADIUS.pill,
    borderWidth: 1,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.08,
    shadowRadius: 12,
    elevation: 4,
  },
  cityPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingHorizontal: SPACING.sm + 2,
    paddingVertical: 6,
    borderRadius: RADIUS.pill,
    borderWidth: 1,
    alignSelf: 'flex-start',
    marginTop: SPACING.sm,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.06,
    shadowRadius: 8,
    elevation: 2,
  },
  cityText: {
    fontSize: 13,
    fontWeight: '600',
  },
  clockPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 999,
    borderWidth: 1,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.08,
    shadowRadius: 8,
    elevation: 3,
  },
  modalBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.35)',
    justifyContent: 'flex-end',
  },
  modalSheet: {
    paddingTop: 10,
    paddingHorizontal: SPACING.lg,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
  },
  modalHandle: {
    width: 44,
    height: 5,
    borderRadius: 3,
    alignSelf: 'center',
    marginBottom: SPACING.md,
  },
  searchBarSlot: {
    marginTop: SPACING.sm,
    paddingHorizontal: SPACING.md,
    zIndex: 100,
  },
  typePillsRow: {
    marginTop: 2,
  },
  typePillsContent: {
    paddingHorizontal: SPACING.md,
    paddingVertical: 2,
    gap: 0,
    alignItems: 'center',
  },
  typePill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 999,
    borderWidth: 1,
    marginRight: 6,
  },
  typePillText: {
    fontSize: 11,
    letterSpacing: -0.1,
  },
  statsBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.sm + 2,
    borderRadius: RADIUS.pill,
    marginTop: SPACING.sm,
    alignSelf: 'flex-start',
    shadowColor: '#F5A623',
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.3,
    shadowRadius: 12,
    elevation: 6,
  },
  statsText: {
    color: '#FFFFFF',
    fontSize: FONT_SIZES.small,
    fontWeight: '700',
  },
  statsBannerNight: {
    backgroundColor: '#111111',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.25,
    shadowRadius: 10,
  },
  nightCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
    backgroundColor: '#F5F5F5',
    borderRadius: 12,
    padding: SPACING.md,
    marginHorizontal: SPACING.md,
    marginTop: SPACING.sm,
    marginBottom: SPACING.xs,
  },
  nightCardIcon: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#EAEAEA',
    alignItems: 'center',
    justifyContent: 'center',
  },
  nightCardTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: '#222222',
    marginBottom: 2,
  },
  nightCardSubtitle: {
    fontSize: 12,
    color: '#555555',
    lineHeight: 16,
  },
  nightCardStrong: {
    color: '#333333',
    fontWeight: '600',
  },
  citySheetOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.45)',
    justifyContent: 'flex-end',
  },
  citySheet: {
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingHorizontal: SPACING.md,
    paddingTop: 6,
    maxHeight: '78%',
  },
  citySheetHandle: {
    alignItems: 'center',
    paddingVertical: 8,
  },
  citySheetHandleBar: {
    width: 40,
    height: 4,
    borderRadius: 2,
  },
  citySheetTitle: {
    fontSize: 18,
    fontWeight: '800',
    marginBottom: SPACING.sm,
    marginHorizontal: 4,
    letterSpacing: -0.2,
  },
  citySheetList: {
    paddingBottom: SPACING.md,
  },
  cityRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
    paddingVertical: 14,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  cityRowIcon: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  cityRowText: {
    fontSize: 15,
    flex: 1,
  },
  sliderCard: {
    marginTop: SPACING.md,
    borderRadius: RADIUS.lg,
    padding: SPACING.md,
    borderWidth: 1,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.08,
    shadowRadius: 12,
    elevation: 4,
  },
  sliderHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: SPACING.xs,
  },
  sliderHeaderLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  sliderTime: {
    fontSize: FONT_SIZES.h4,
    fontWeight: '700',
  },
  livePill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: SPACING.sm,
    paddingVertical: 3,
    borderRadius: RADIUS.pill,
  },
  liveDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: '#FFFFFF',
  },
  liveText: {
    color: '#FFFFFF',
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 0.5,
  },
  slider: {
    width: '100%',
    height: 32,
  },
  sliderLabels: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  dateTabsScroll: {
    marginHorizontal: 0,
    marginTop: 4,
    marginBottom: SPACING.sm,
    maxHeight: 58,
  },
  dateTabsContent: {
    paddingHorizontal: SPACING.md,
    gap: 8,
    alignItems: 'center',
  },
  dateTab: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 12,
    marginRight: 6,
    minWidth: 52,
  },
  dateTabLabel: {
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 0.2,
  },
  dateTabNum: {
    fontSize: 14,
    fontWeight: '800',
    letterSpacing: -0.3,
    marginTop: 1,
  },
  sliderLabel: {
    fontSize: FONT_SIZES.caption,
    fontWeight: '500',
  },
  bottomSheet: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    height: '40%',
    borderTopLeftRadius: 32,
    borderTopRightRadius: 32,
    shadowOffset: { width: 0, height: -4 },
    shadowOpacity: 0.1,
    shadowRadius: 20,
    elevation: 10,
  },
  handle: {
    alignItems: 'center',
    paddingTop: SPACING.sm,
    paddingBottom: SPACING.xs,
  },
  handleBar: {
    width: 40,
    height: 4,
    borderRadius: 2,
  },
  filtersWrap: {
    paddingVertical: SPACING.sm,
  },
  filtersContent: {
    paddingHorizontal: SPACING.md,
    gap: SPACING.xs,
    alignItems: 'center',
  },
  filterChip: {
    paddingHorizontal: 14,
    paddingVertical: 5,
    borderRadius: 20,
  },
  filterText: {
    fontSize: 12,
  },
  divider: {
    width: 1,
    height: 20,
    marginHorizontal: SPACING.xs,
  },
  listContent: {
    paddingHorizontal: SPACING.md,
    paddingBottom: SPACING.xl,
  },
  listHeader: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    marginBottom: SPACING.sm,
  },
  listTitle: {
    fontSize: FONT_SIZES.h4,
    fontWeight: '700',
  },
  listSubtitle: {
    fontSize: FONT_SIZES.small,
    fontWeight: '500',
  },
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: SPACING.xl,
  },
  loadingText: {
    marginTop: SPACING.sm,
    fontSize: FONT_SIZES.small,
  },
  emptyState: {
    alignItems: 'center',
    padding: SPACING.xl,
    gap: SPACING.sm,
  },
  emptyText: {
    fontSize: FONT_SIZES.body,
    textAlign: 'center',
  },
  gpsBtn: {
    position: 'absolute',
    right: SPACING.md,
    bottom: 240,
    width: 48,
    height: 48,
    borderRadius: 24,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.15,
    shadowRadius: 12,
    elevation: 6,
    zIndex: 50,
  },
  themeBtn: {
    position: 'absolute',
    right: SPACING.md,
    bottom: 296,
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.12,
    shadowRadius: 10,
    elevation: 5,
    zIndex: 50,
  },
  profileBtn: {
    position: 'absolute',
    right: SPACING.md,
    bottom: 348,
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.12,
    shadowRadius: 10,
    elevation: 5,
    zIndex: 50,
    overflow: 'hidden',
  },
  profileAvatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
  },
  addFab: {
    position: 'absolute',
    right: SPACING.md,
    bottom: 170,
    width: 56,
    height: 56,
    borderRadius: 28,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#F5A623',
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.35,
    shadowRadius: 14,
    elevation: 8,
    zIndex: 50,
  },
  proRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.md,
    paddingVertical: SPACING.md,
    paddingHorizontal: SPACING.md,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  proRowTitle: {
    fontSize: 14,
    fontWeight: '700',
    letterSpacing: -0.2,
  },
  proRowSub: {
    fontSize: 11,
    fontWeight: '500',
    marginTop: 1,
  },
  sliderHeaderRight: {
    flexDirection: 'row',
    alignItems: 'center',
  },
});
