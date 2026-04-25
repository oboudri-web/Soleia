/**
 * SunTerrace - Terrace Detail Screen
 * Shows: full photo, details, description IA, sun schedule, hourly forecast, time slider.
 */
import React, { useEffect, useState, useCallback, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Image,
  TouchableOpacity,
  ActivityIndicator,
  Linking,
  Platform,
  Alert,
  Share,
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import Slider from '@react-native-community/slider';
import { LinearGradient } from 'expo-linear-gradient';
import * as ImagePicker from 'expo-image-picker';
import { captureRef } from 'react-native-view-shot';
import * as Sharing from 'expo-sharing';
import { useFavorites } from '../../src/AuthContext';
import { translateWeekdayDescription, isOpenAt } from '../../src/utils/openingHours';

import { useTheme } from '../../src/ThemeContext';
import { SPACING, FONT_SIZES, RADIUS, TYPE_LABELS, TYPE_ICONS } from '../../src/theme';
import { api, type TerraceDetail } from '../../src/api';
import { formatTimeFr, hhmmToFr } from '../../src/utils/time';
import SunTimeline from '../../src/components/SunTimeline';

export default function TerraceDetailScreen() {
  const router = useRouter();
  const { theme, isDark } = useTheme();
  const insets = useSafeAreaInsets();
  const params = useLocalSearchParams<{ id: string; at_time?: string }>();
  const id = params.id as string;

  const [terrace, setTerrace] = useState<TerraceDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [reportType, setReportType] = useState<null | 'confirmed' | 'wrong_orientation' | 'no_terrace'>(null);
  const [reportSending, setReportSending] = useState(false);
  const [photoUploading, setPhotoUploading] = useState(false);
  const [photoUploaded, setPhotoUploaded] = useState(false);
  const [sharing, setSharing] = useState(false);
  const { isFavorite, toggleFavorite } = useFavorites();
  const favorited = isFavorite(id);
  const shareCardRef = useRef<View>(null);

  const onToggleFavorite = useCallback(async () => {
    try {
      await toggleFavorite(id);
    } catch {}
  }, [id, toggleFavorite]);

  const now = new Date();
  const [currentMinutes, setCurrentMinutes] = useState(
    now.getHours() * 60 + now.getMinutes()
  );
  const [isLiveMode, setIsLiveMode] = useState(!params.at_time);

  const buildAtTime = useCallback(() => {
    const d = new Date();
    const h = Math.floor(currentMinutes / 60);
    const m = currentMinutes % 60;
    d.setHours(h, m, 0, 0);
    const pad = (n: number) => n.toString().padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(h)}:${pad(m)}:00`;
  }, [currentMinutes]);

  const loadTerrace = useCallback(async () => {
    try {
      const atTime = isLiveMode ? undefined : buildAtTime();
      const result = await api.getTerrace(id, atTime);
      setTerrace(result);
      if (!result.ai_description) {
        // Fire-and-forget AI generation
        setGenerating(true);
        api.generateDescription(id)
          .then((r) => setTerrace((prev) => (prev ? { ...prev, ai_description: r.ai_description } : prev)))
          .catch(() => {})
          .finally(() => setGenerating(false));
      }
    } catch (e) {
      console.warn('Failed to load terrace', e);
    } finally {
      setLoading(false);
    }
  }, [id, isLiveMode, buildAtTime]);

  useEffect(() => {
    loadTerrace();
  }, [loadTerrace]);

  const formatTime = (mins: number) => formatTimeFr(mins);

  const openDirections = () => {
    if (!terrace) return;
    const url = Platform.select({
      ios: `maps://app?daddr=${terrace.lat},${terrace.lng}`,
      android: `geo:${terrace.lat},${terrace.lng}?q=${terrace.lat},${terrace.lng}(${encodeURIComponent(terrace.name)})`,
      web: `https://www.google.com/maps/dir/?api=1&destination=${terrace.lat},${terrace.lng}`,
      default: `https://www.google.com/maps/dir/?api=1&destination=${terrace.lat},${terrace.lng}`,
    });
    Linking.openURL(url!).catch(() => {});
  };

  const openGoogleMaps = () => {
    if (!terrace) return;
    const q = encodeURIComponent(`${terrace.name} ${terrace.address || terrace.city}`);
    const url = `https://www.google.com/maps/search/?api=1&query=${q}&query_place_id=${terrace.lat},${terrace.lng}`;
    Linking.openURL(url).catch(() => {});
  };

  const openFoursquare = () => {
    if (!terrace?.google_maps_uri) return;
    Linking.openURL(terrace.google_maps_uri).catch(() => {});
  };

  const sendReport = async (type: 'confirmed' | 'wrong_orientation' | 'no_terrace') => {
    if (reportSending || reportType) return;
    setReportSending(true);
    try {
      await api.reportTerrace(id, type);
      setReportType(type);
    } catch (e) {
      Alert.alert('Erreur', "Impossible d'envoyer le signalement.");
    } finally {
      setReportSending(false);
    }
  };

  const pickAndUploadPhoto = async () => {
    if (photoUploading) return;
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        Alert.alert('Accès refusé', 'Autorisez l\'accès aux photos pour contribuer.');
        return;
      }
      const res = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        base64: true,
        quality: 0.55,
        allowsEditing: true,
        aspect: [4, 3],
      });
      if (res.canceled || !res.assets[0]?.base64) return;
      setPhotoUploading(true);
      await api.uploadTerracePhoto(id, res.assets[0].base64);
      setPhotoUploaded(true);
      Alert.alert('Merci ! 🌞', 'Ta photo a bien été ajoutée.');
    } catch (e) {
      Alert.alert('Erreur', "Envoi de la photo impossible.");
    } finally {
      setPhotoUploading(false);
    }
  };

  const openPhone = () => {
    if (!terrace?.phone_number) return;
    const normalised = terrace.phone_number.replace(/\s+/g, '');
    Linking.openURL(`tel:${normalised}`).catch(() => {});
  };

  const openWebsite = () => {
    if (!terrace?.website_uri) return;
    Linking.openURL(terrace.website_uri).catch(() => {});
  };

  const shareTerrace = async () => {
    if (sharing || !terrace) return;
    setSharing(true);
    try {
      if (Platform.OS === 'web') {
        // Web: use Web Share API with URL only (view-shot is not reliable on web)
        const url = typeof window !== 'undefined' ? window.location.href : '';
        const message = `${terrace.name} · ${terrace.city} — Soleia ☀️`;
        if (typeof navigator !== 'undefined' && (navigator as any).share) {
          await (navigator as any).share({ title: terrace.name, text: message, url });
        } else {
          // Fallback: copy to clipboard + alert
          try {
            if (typeof navigator !== 'undefined' && (navigator as any).clipboard) {
              await (navigator as any).clipboard.writeText(`${message}\n${url}`);
              Alert.alert('Lien copié', 'Le lien a été copié dans ton presse-papier.');
            } else {
              Alert.alert('Partage', `${message}\n${url}`);
            }
          } catch {
            Alert.alert('Partage', `${message}\n${url}`);
          }
        }
        return;
      }

      // Native: capture the share card 1080x1080 and share via OS sheet
      if (!shareCardRef.current) {
        // Fallback to plain text share
        await Share.share({
          title: terrace.name,
          message: `${terrace.name} · ${terrace.city} — découvre cette terrasse ensoleillée sur Soleia ☀️`,
        });
        return;
      }
      const uri = await captureRef(shareCardRef.current, {
        format: 'png',
        quality: 1,
        width: 1080,
        height: 1080,
        result: 'tmpfile',
      });
      const canShareFile = await Sharing.isAvailableAsync();
      if (canShareFile) {
        await Sharing.shareAsync(uri, {
          mimeType: 'image/png',
          dialogTitle: terrace.name,
          UTI: 'public.png',
        });
      } else {
        await Share.share({
          url: uri,
          message: `${terrace.name} · ${terrace.city}`,
          title: terrace.name,
        });
      }
    } catch (e) {
      Alert.alert('Erreur', "Partage impossible.");
    } finally {
      setSharing(false);
    }
  };

  if (loading || !terrace) {
    return (
      <View style={[styles.loadingContainer, { backgroundColor: theme.background }]}>
        <ActivityIndicator size="large" color={theme.primary} />
      </View>
    );
  }

  const statusColor =
    terrace.sun_status === 'sunny'
      ? theme.markerSunny
      : terrace.sun_status === 'soon'
      ? theme.markerSoon
      : theme.markerShade;

  const sunnyHoursToday = terrace.sun_schedule_today?.sunny_hours || [];
  const totalSunMin = terrace.sun_schedule_today?.total_minutes || 0;
  const totalSunHours = Math.floor(totalSunMin / 60);
  const totalSunRemaining = totalSunMin % 60;

  // Determine open/closed state at the current (or planned) time
  const atTimeForStatus = isLiveMode
    ? new Date()
    : (() => {
        const d = new Date();
        d.setHours(Math.floor(currentMinutes / 60), currentMinutes % 60, 0, 0);
        return d;
      })();
  const openState = isOpenAt(terrace.opening_hours as any, atTimeForStatus); // true | false | null
  const isClosed = openState === false;

  // Override sun status visual if closed
  const effectiveStatusColor = isClosed ? '#9E9E9E' : statusColor;
  const effectiveStatusIcon: any = isClosed
    ? 'lock-closed'
    : terrace.sun_status === 'sunny'
    ? 'sunny'
    : terrace.sun_status === 'soon'
    ? 'time'
    : 'moon';
  const effectiveStatusLabel = isClosed
    ? 'Fermé maintenant'
    : terrace.sun_status === 'sunny'
    ? 'Au soleil maintenant'
    : terrace.sun_status === 'soon'
    ? 'Soleil bientôt'
    : "À l'ombre";

  return (
    <View style={[styles.container, { backgroundColor: theme.background }]}>
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ paddingBottom: 120 }}
        showsVerticalScrollIndicator={false}
      >
        {/* Hero image */}
        <View style={styles.heroContainer}>
          <Image source={{ uri: terrace.photo_url }} style={styles.hero} />
          <LinearGradient
            colors={['rgba(0,0,0,0.4)', 'transparent', 'rgba(0,0,0,0.6)']}
            style={StyleSheet.absoluteFill}
          />

          {/* Close button + Favorite */}
          <SafeAreaView style={styles.heroTopBar} edges={['top']}>
            <TouchableOpacity
              testID="btn-close"
              activeOpacity={0.8}
              onPress={() => router.back()}
              style={styles.closeBtn}
            >
              <Ionicons name="close" size={22} color="#000" />
            </TouchableOpacity>

            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <TouchableOpacity
                testID="btn-favorite"
                activeOpacity={0.8}
                onPress={onToggleFavorite}
                style={styles.closeBtn}
              >
                <Ionicons
                  name={favorited ? 'heart' : 'heart-outline'}
                  size={22}
                  color={favorited ? '#FF3B30' : '#000'}
                />
              </TouchableOpacity>

              <View style={[styles.heroStatus, { backgroundColor: effectiveStatusColor }]}>
                <Ionicons
                  name={effectiveStatusIcon}
                  size={14}
                  color="#FFFFFF"
                />
                <Text style={styles.heroStatusText}>
                  {effectiveStatusLabel}
                </Text>
              </View>
            </View>
          </SafeAreaView>

          {/* Title overlay */}
          <View style={styles.heroBottom}>
            <Text
              style={[
                styles.heroName,
                { fontFamily: 'Fraunces_400Regular_Italic' },
              ]}
              testID="terrace-name"
            >
              {terrace.name}
            </Text>
            <View style={styles.heroMetaRow}>
              <View style={styles.heroTypeTag}>
                <Ionicons name={TYPE_ICONS[terrace.type] as any} size={12} color="#FFFFFF" />
                <Text style={styles.heroMetaText}>{TYPE_LABELS[terrace.type]}</Text>
              </View>
              <Text style={styles.heroMetaDot}>·</Text>
              <View style={styles.heroRating}>
                <Ionicons name="star" size={14} color="#F5A623" />
                <Text style={styles.heroRatingBig}>
                  {terrace.google_rating.toFixed(1)}
                </Text>
                {terrace.google_ratings_count && terrace.google_ratings_count > 0 ? (
                  <Text style={styles.heroRatingCount}>
                    ({terrace.google_ratings_count} avis)
                  </Text>
                ) : null}
              </View>
              {terrace.arrondissement && (
                <>
                  <Text style={styles.heroMetaDot}>·</Text>
                  <Text style={styles.heroMetaText}>{terrace.arrondissement}</Text>
                </>
              )}
            </View>
            {(terrace.terrace_covered === true || terrace.terrace_capacity === 'large') && (
              <View style={styles.heroBadges} testID="terrace-badges">
                {terrace.terrace_covered === true && (
                  <View style={[styles.heroBadge, styles.heroBadgeCovered]}>
                    <Ionicons name="umbrella" size={11} color="#0369A1" />
                    <Text style={[styles.heroBadgeText, { color: '#0369A1' }]}>
                      Terrasse couverte
                    </Text>
                  </View>
                )}
                {terrace.terrace_capacity === 'large' && (
                  <View style={[styles.heroBadge, styles.heroBadgeLarge]}>
                    <Ionicons name="people" size={11} color="#166534" />
                    <Text style={[styles.heroBadgeText, { color: '#166534' }]}>
                      Grande terrasse
                    </Text>
                  </View>
                )}
              </View>
            )}
          </View>
        </View>

        {/* Sun summary card */}
        <View
          style={[
            styles.sunCard,
            { backgroundColor: theme.surface, borderColor: theme.border },
          ]}
          testID="sun-summary"
        >
          <View style={styles.sunCardHeader}>
            <Ionicons name="sunny" size={22} color={theme.primary} />
            <Text style={[styles.sunCardTitle, { color: theme.text }]}>
              Aujourd'hui
            </Text>
            {totalSunMin > 0 && (
              <Text style={[styles.sunTotalBadge, { backgroundColor: theme.primary }]}>
                {totalSunHours > 0 ? `${totalSunHours}h` : ''}
                {totalSunRemaining > 0 ? `${totalSunRemaining.toString().padStart(totalSunHours > 0 ? 2 : 1, '0')}` : totalSunHours === 0 ? '0h' : ''}
                {' de soleil'}
              </Text>
            )}
          </View>
          {sunnyHoursToday.length > 0 ? (
            <>
              <Text style={[styles.sunDurationLine, { color: theme.text }]} testID="sun-duration">
                {totalSunHours > 0 ? `${totalSunHours}h` : ''}
                {totalSunRemaining > 0
                  ? totalSunHours > 0
                    ? totalSunRemaining.toString().padStart(2, '0')
                    : `${totalSunRemaining} min`
                  : ''}
                {' de soleil aujourd\'hui'}
              </Text>
              <View style={styles.sunRanges}>
                {sunnyHoursToday.map((h, i) => (
                  <View key={i} style={[styles.sunRange, { backgroundColor: theme.surfaceSecondary }]}>
                    <Ionicons name="sunny" size={12} color={theme.primary} />
                    <Text style={[styles.sunRangeText, { color: theme.text }]}>
                      Soleil de {hhmmToFr(h.start)} à {hhmmToFr(h.end)}
                    </Text>
                  </View>
                ))}
              </View>
            </>
          ) : (
            <View style={styles.noSunRow} testID="no-sun-today">
              <Ionicons name="moon" size={18} color={theme.textSecondary} />
              <Text style={[styles.sunNoneText, { color: theme.textSecondary }]}>
                Pas de soleil aujourd'hui · Orientation {terrace.orientation_label.toLowerCase()}
              </Text>
            </View>
          )}

          {terrace.sunny_until && terrace.sun_status === 'sunny' && !isClosed && (
            <View
              style={[styles.currentBanner, { backgroundColor: theme.primary }]}
              testID="current-sun-banner"
            >
              <Ionicons name="time" size={14} color="#FFFFFF" />
              <Text style={styles.currentBannerText}>
                Soleil encore jusqu'à {hhmmToFr(terrace.sunny_until)}
              </Text>
            </View>
          )}
          {terrace.next_sunny_time && terrace.sun_status === 'soon' && !isClosed && (
            <View
              style={[styles.currentBanner, { backgroundColor: theme.markerSoon }]}
            >
              <Ionicons name="time" size={14} color="#FFFFFF" />
              <Text style={styles.currentBannerText}>
                Prochain soleil à {hhmmToFr(terrace.next_sunny_time)}
              </Text>
            </View>
          )}
          {isClosed && (
            <View
              style={[styles.currentBanner, { backgroundColor: '#9E9E9E' }]}
              testID="closed-banner"
            >
              <Ionicons name="lock-closed" size={14} color="#FFFFFF" />
              <Text style={styles.currentBannerText}>
                Fermé maintenant
              </Text>
            </View>
          )}
        </View>

        {/* Sun timeline (grayed out if closed) */}
        <View style={{ opacity: isClosed ? 0.45 : 1 }} pointerEvents={isClosed ? 'none' : 'auto'}>
          <SunTimeline
            sunnyRanges={sunnyHoursToday.map((h) => ({ start: h.start, end: h.end }))}
            currentMinutes={currentMinutes}
            onChange={(m) => {
              setCurrentMinutes(m);
              setIsLiveMode(false);
              // debounce reload via a short timeout? we reload on idle — just call loadTerrace
              loadTerrace();
            }}
            isLive={isLiveMode}
            onLive={() => {
              const n = new Date();
              setCurrentMinutes(n.getHours() * 60 + n.getMinutes());
              setIsLiveMode(true);
              loadTerrace();
            }}
          />
        </View>

        {/* 3D shadow analysis badge (Nantes pilot) */}
        {terrace.shadow_analyzed ? (
          <View
            style={[
              styles.shadowBadge,
              {
                backgroundColor: theme.surface,
                borderColor: theme.primary + '33',
              },
            ]}
            testID="shadow-3d-badge"
          >
            <View style={[styles.shadowBadgeIcon, { backgroundColor: theme.primary + '1A' }]}>
              <Ionicons name="cube" size={18} color={theme.primary} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={[styles.shadowBadgeTitle, { color: theme.text }]}>
                Calcul 3D précis
              </Text>
              <Text style={[styles.shadowBadgeSub, { color: theme.textSecondary }]}>
                {terrace.shadow_buildings_count
                  ? `Analyse des ombres sur ${terrace.shadow_buildings_count} bâtiments alentour`
                  : "Analyse des ombres sur les bâtiments alentour"}
                {terrace.shadow_override ? ' · orientation corrigée' : ''}
              </Text>
            </View>
            <View style={[styles.shadowBadgeChip, { backgroundColor: theme.primary }]}>
              <Text style={styles.shadowBadgeChipText}>3D</Text>
            </View>
          </View>
        ) : null}

        {/* Hourly forecast */}
        <View style={styles.hourlySection}>
          <View style={[styles.sectionHeader, { paddingHorizontal: SPACING.md }]}>
            <Ionicons name="calendar-outline" size={18} color={theme.primary} />
            <Text style={[styles.sectionTitle, { color: theme.text }]}>
              Heure par heure
            </Text>
          </View>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ paddingHorizontal: SPACING.md, gap: SPACING.sm }}
          >
            {terrace.hourly_forecast.map((h) => (
              <View
                key={h.hour}
                style={[
                  styles.hourCard,
                  {
                    backgroundColor: h.is_sunny ? theme.primary : theme.surfaceSecondary,
                  },
                ]}
                testID={`hour-${h.hour}`}
              >
                <Text
                  style={[
                    styles.hourLabel,
                    { color: h.is_sunny ? '#FFFFFF' : theme.textSecondary },
                  ]}
                >
                  {hhmmToFr(h.hour)}
                </Text>
                <Ionicons
                  name={h.is_sunny ? 'sunny' : h.sun_altitude < 0 ? 'moon' : 'cloud-outline'}
                  size={20}
                  color={h.is_sunny ? '#FFFFFF' : theme.textTertiary}
                />
                <Text
                  style={[
                    styles.hourAlt,
                    { color: h.is_sunny ? '#FFFFFF' : theme.textTertiary },
                  ]}
                >
                  {h.sun_altitude > 0 ? `${Math.round(h.sun_altitude)}°` : '—'}
                </Text>
              </View>
            ))}
          </ScrollView>
        </View>

        {/* AI Description */}
        <View
          style={[styles.section, { backgroundColor: theme.surface, borderColor: theme.border }]}
        >
          <View style={styles.sectionHeader}>
            <Ionicons name="sparkles" size={18} color={theme.primary} />
            <Text style={[styles.sectionTitle, { color: theme.text }]}>
              Description IA
            </Text>
          </View>
          {terrace.ai_description ? (
            <Text style={[styles.descriptionText, { color: theme.text }]}>
              {terrace.ai_description}
            </Text>
          ) : generating ? (
            <View style={styles.generatingRow}>
              <ActivityIndicator size="small" color={theme.primary} />
              <Text style={[styles.generatingText, { color: theme.textSecondary }]}>
                Génération par Claude...
              </Text>
            </View>
          ) : (
            <Text style={[styles.descriptionText, { color: theme.textSecondary }]}>
              Terrasse {terrace.orientation_label.toLowerCase()}
              {terrace.has_cover ? ', avec auvent' : ', en plein air'}, capacité d'environ{' '}
              {terrace.capacity_estimate} places.
            </Text>
          )}
        </View>

        {/* Info grid */}
        <View style={styles.infoGrid}>
          <View style={[styles.infoCard, { backgroundColor: theme.surface, borderColor: theme.border }]}>
            <Ionicons name="compass" size={18} color={theme.primary} />
            <Text style={[styles.infoLabel, { color: theme.textSecondary }]}>Orientation</Text>
            <Text style={[styles.infoValue, { color: theme.text }]}>{terrace.orientation_label}</Text>
            <Text style={[styles.infoSub, { color: theme.textTertiary }]}>
              {terrace.orientation_degrees}°
            </Text>
          </View>
          <View style={[styles.infoCard, { backgroundColor: theme.surface, borderColor: theme.border }]}>
            <Ionicons name="people" size={18} color={theme.primary} />
            <Text style={[styles.infoLabel, { color: theme.textSecondary }]}>Capacité</Text>
            <Text style={[styles.infoValue, { color: theme.text }]}>~{terrace.capacity_estimate}</Text>
            <Text style={[styles.infoSub, { color: theme.textTertiary }]}>places</Text>
          </View>
          <View style={[styles.infoCard, { backgroundColor: theme.surface, borderColor: theme.border }]}>
            <Ionicons name={terrace.has_cover ? 'umbrella' : 'cloud'} size={18} color={theme.primary} />
            <Text style={[styles.infoLabel, { color: theme.textSecondary }]}>Aménagement</Text>
            <Text style={[styles.infoValue, { color: theme.text }]}>
              {terrace.has_cover ? 'Couvert' : 'Ouvert'}
            </Text>
            <Text style={[styles.infoSub, { color: theme.textTertiary }]}>
              {terrace.has_cover ? 'auvent' : 'plein air'}
            </Text>
          </View>
        </View>

        {/* Address */}
        <View
          style={[styles.section, { backgroundColor: theme.surface, borderColor: theme.border }]}
        >
          <View style={styles.sectionHeader}>
            <Ionicons name="location" size={18} color={theme.primary} />
            <Text style={[styles.sectionTitle, { color: theme.text }]}>Adresse</Text>
          </View>
          <Text style={[styles.descriptionText, { color: theme.text }]}>
            {terrace.address}
          </Text>

          <View style={styles.externalLinks}>
            <TouchableOpacity
              testID="btn-open-gmaps"
              onPress={openGoogleMaps}
              activeOpacity={0.75}
              style={[styles.externalLinkBtn, { borderColor: theme.border }]}
            >
              <Ionicons name="map" size={14} color={theme.textSecondary} />
              <Text style={[styles.externalLinkText, { color: theme.textSecondary }]}>
                Voir sur Google Maps
              </Text>
            </TouchableOpacity>

            {terrace.google_maps_uri ? (
              <TouchableOpacity
                testID="btn-open-foursquare"
                onPress={openFoursquare}
                activeOpacity={0.75}
                style={[styles.externalLinkBtn, { borderColor: theme.border }]}
              >
                <Ionicons name="compass" size={14} color={theme.textSecondary} />
                <Text style={[styles.externalLinkText, { color: theme.textSecondary }]}>
                  Page Google
                </Text>
              </TouchableOpacity>
            ) : null}
          </View>
        </View>

        {/* Infos pratiques (Google Places Details) */}
        {(terrace.opening_hours || terrace.phone_number || terrace.website_uri || terrace.price_level != null) ? (
          <View
            style={[styles.section, { backgroundColor: theme.surface, borderColor: theme.border }]}
            testID="infos-pratiques"
          >
            <View style={styles.sectionHeader}>
              <Ionicons name="information-circle-outline" size={18} color={theme.primary} />
              <Text style={[styles.sectionTitle, { color: theme.text }]}>Infos pratiques</Text>
              {terrace.price_level != null ? (
                <View style={[styles.pricePill, { backgroundColor: theme.surfaceSecondary }]}>
                  <Text style={[styles.pricePillText, { color: theme.primary }]}>
                    {'€'.repeat(Math.max(1, terrace.price_level))}
                  </Text>
                </View>
              ) : null}
            </View>

            {terrace.opening_hours?.weekday_descriptions?.length ? (
              <View style={styles.hoursList}>
                {(() => {
                  // Put today's day first (JS getDay: 0=Sun, Places uses 0=Mon)
                  const descs = terrace.opening_hours.weekday_descriptions;
                  const jsDay = new Date().getDay();
                  const today = jsDay === 0 ? 6 : jsDay - 1; // 0=Mon
                  return descs.map((line, i) => (
                    <Text
                      key={i}
                      style={[
                        styles.hoursLine,
                        i === today
                          ? { color: theme.text, fontWeight: '700' }
                          : { color: theme.textSecondary },
                      ]}
                    >
                      {translateWeekdayDescription(line)}
                    </Text>
                  ));
                })()}
              </View>
            ) : null}

            {terrace.phone_number ? (
              <TouchableOpacity
                activeOpacity={0.75}
                onPress={openPhone}
                style={styles.infoRow}
                testID="infos-phone"
              >
                <Ionicons name="call" size={14} color={theme.primary} />
                <Text style={[styles.infoText, { color: theme.text }]}>{terrace.phone_number}</Text>
              </TouchableOpacity>
            ) : null}

            {terrace.website_uri ? (
              <TouchableOpacity
                activeOpacity={0.75}
                onPress={openWebsite}
                style={styles.infoRow}
                testID="infos-website"
              >
                <Ionicons name="globe-outline" size={14} color={theme.primary} />
                <Text
                  style={[styles.infoText, { color: theme.text }]}
                  numberOfLines={1}
                  ellipsizeMode="tail"
                >
                  {terrace.website_uri.replace(/^https?:\/\//, '').replace(/\/$/, '')}
                </Text>
              </TouchableOpacity>
            ) : null}
          </View>
        ) : null}

        {/* Community actions - crowdsourcing */}
        <View
          style={[styles.section, { backgroundColor: theme.surface, borderColor: theme.border }]}
          testID="community-section"
        >
          <View style={styles.sectionHeader}>
            <Ionicons name="people" size={18} color={theme.primary} />
            <Text style={[styles.sectionTitle, { color: theme.text }]}>
              Aider la communauté
            </Text>
          </View>
          <Text style={[styles.communityHint, { color: theme.textSecondary }]}>
            Cette terrasse est-elle conforme à la réalité ?
          </Text>
          <View style={styles.reportRow}>
            {[
              { key: 'confirmed', label: 'Confirmer', icon: 'checkmark-circle', color: '#16A34A' },
              { key: 'wrong_orientation', label: 'Orientation', icon: 'compass', color: '#EA580C' },
              { key: 'no_terrace', label: 'Pas de terrasse', icon: 'close-circle', color: '#DC2626' },
            ].map((r) => {
              const active = reportType === r.key;
              return (
                <TouchableOpacity
                  key={r.key}
                  testID={`report-${r.key}`}
                  activeOpacity={0.8}
                  disabled={!!reportType || reportSending}
                  onPress={() => sendReport(r.key as any)}
                  style={[
                    styles.reportPill,
                    {
                      backgroundColor: active ? r.color : theme.surfaceSecondary,
                      borderColor: active ? r.color : theme.border,
                      opacity: reportType && !active ? 0.45 : 1,
                    },
                  ]}
                >
                  <Ionicons
                    name={r.icon as any}
                    size={14}
                    color={active ? '#FFF' : r.color}
                  />
                  <Text
                    style={[
                      styles.reportPillText,
                      { color: active ? '#FFF' : theme.text },
                    ]}
                    numberOfLines={1}
                  >
                    {r.label}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>
          {reportType ? (
            <Text style={[styles.reportThanks, { color: theme.primary }]}>
              Merci pour ton retour 🌞
            </Text>
          ) : null}

          <TouchableOpacity
            testID="btn-add-photo"
            activeOpacity={0.85}
            disabled={photoUploading || photoUploaded}
            onPress={pickAndUploadPhoto}
            style={[
              styles.photoUploadBtn,
              {
                borderColor: photoUploaded ? theme.primary : theme.border,
                backgroundColor: theme.surfaceSecondary,
              },
            ]}
          >
            {photoUploading ? (
              <ActivityIndicator size="small" color={theme.primary} />
            ) : (
              <Ionicons
                name={photoUploaded ? 'checkmark-circle' : 'camera'}
                size={18}
                color={theme.primary}
              />
            )}
            <Text style={[styles.photoUploadText, { color: theme.text }]}>
              {photoUploaded ? 'Photo ajoutée, merci !' : photoUploading ? 'Envoi en cours...' : 'Ajouter une photo'}
            </Text>
          </TouchableOpacity>
        </View>
      </ScrollView>

      {/* CTA row: Y aller / Réserver / Téléphone / Partager */}
      <View
        style={[
          styles.ctaBar,
          { backgroundColor: theme.background, borderTopColor: theme.border, paddingBottom: Math.max(insets.bottom, SPACING.md) },
        ]}
      >
        <TouchableOpacity
          testID="btn-y-aller"
          activeOpacity={0.85}
          onPress={openDirections}
          style={[styles.ctaPrimary, { backgroundColor: theme.text }]}
        >
          <Ionicons name="navigate" size={17} color="#FFFFFF" />
          <Text style={styles.ctaPrimaryText}>Y aller</Text>
        </TouchableOpacity>

        {terrace.website_uri ? (
          <TouchableOpacity
            testID="btn-reserve"
            activeOpacity={0.8}
            onPress={openWebsite}
            style={[styles.ctaSecondary, { backgroundColor: theme.surfaceSecondary, borderColor: theme.border }]}
          >
            <Ionicons name="calendar-outline" size={17} color={theme.primary} />
          </TouchableOpacity>
        ) : null}

        {terrace.phone_number ? (
          <TouchableOpacity
            testID="btn-phone"
            activeOpacity={0.8}
            onPress={openPhone}
            style={[styles.ctaSecondary, { backgroundColor: theme.surfaceSecondary, borderColor: theme.border }]}
          >
            <Ionicons name="call" size={17} color={theme.primary} />
          </TouchableOpacity>
        ) : null}

        <TouchableOpacity
          testID="btn-share"
          activeOpacity={0.8}
          onPress={shareTerrace}
          disabled={sharing}
          style={[styles.ctaSecondary, { backgroundColor: theme.surfaceSecondary, borderColor: theme.border }]}
        >
          {sharing ? (
            <ActivityIndicator size="small" color={theme.primary} />
          ) : (
            <Ionicons name="share-outline" size={17} color={theme.primary} />
          )}
        </TouchableOpacity>
      </View>

      {/* Hidden share card rendered offscreen for view-shot (mobile only) */}
      {Platform.OS !== 'web' ? (
        <View
          collapsable={false}
          style={styles.shareCardWrapper}
          pointerEvents="none"
        >
          <View ref={shareCardRef} collapsable={false} style={styles.shareCard}>
            <LinearGradient
              colors={['#FFB84D', '#F5A623', '#E08300']}
              style={StyleSheet.absoluteFill}
            />
            {/* Decorative sun */}
            <View style={styles.shareCardSunWrap}>
              <View style={styles.shareCardSun} />
            </View>
            {/* Content */}
            <View style={styles.shareCardContent}>
              <Text style={styles.shareCardLogo}>Soleia</Text>
              <View style={{ flex: 1 }} />
              <Text style={styles.shareCardKicker}>Terrasse au soleil</Text>
              <Text style={styles.shareCardName} numberOfLines={2}>
                {terrace.name}
              </Text>
              <Text style={styles.shareCardCity}>{terrace.city}</Text>
              <View style={styles.shareCardStatusPill}>
                <View style={styles.shareCardStatusDot} />
                <Text style={styles.shareCardStatusText}>
                  {terrace.sun_status === 'sunny'
                    ? 'Au soleil maintenant'
                    : terrace.sun_status === 'soon'
                    ? 'Bientôt au soleil'
                    : terrace.sunny_until || terrace.next_sunny_time
                    ? 'À l\'ombre pour l\'instant'
                    : 'Terrasse ensoleillée'}
                </Text>
              </View>
              <Text style={styles.shareCardFoot}>soleia.app · trouve-la sur l'app</Text>
            </View>
          </View>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  loadingContainer: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  heroContainer: {
    height: 320,
    position: 'relative',
  },
  hero: {
    width: '100%',
    height: '100%',
    resizeMode: 'cover',
  },
  heroTopBar: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: SPACING.md,
  },
  closeBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.95)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  heroStatus: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: SPACING.sm + 2,
    paddingVertical: 6,
    borderRadius: RADIUS.pill,
  },
  heroStatusText: {
    color: '#FFFFFF',
    fontSize: FONT_SIZES.caption,
    fontWeight: '700',
  },
  heroBottom: {
    position: 'absolute',
    bottom: SPACING.md,
    left: SPACING.md,
    right: SPACING.md,
  },
  heroName: {
    color: '#FFFFFF',
    fontSize: 32,
    fontWeight: '400',
    letterSpacing: -0.5,
    marginBottom: 6,
  },
  heroMetaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    flexWrap: 'wrap',
  },
  heroTypeTag: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
  },
  heroRating: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  heroRatingBig: {
    color: '#F5A623',
    fontSize: 16,
    fontWeight: '800',
  },
  heroRatingCount: {
    color: 'rgba(255,255,255,0.75)',
    fontSize: 11,
    fontWeight: '500',
    marginLeft: 2,
  },
  heroBadges: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginTop: 8,
  },
  heroBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 9,
    paddingVertical: 4,
    borderRadius: 999,
  },
  heroBadgeCovered: {
    backgroundColor: '#E0F2FE',
  },
  heroBadgeLarge: {
    backgroundColor: '#DCFCE7',
  },
  heroBadgeText: {
    fontSize: 11,
    fontWeight: '700',
  },
  externalLinks: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: SPACING.sm,
  },
  externalLinkBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    borderWidth: 1,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
  },
  externalLinkText: {
    fontSize: 11,
    fontWeight: '600',
  },
  heroMetaText: {
    color: '#FFFFFF',
    fontSize: FONT_SIZES.small,
    fontWeight: '600',
  },
  heroMetaDot: {
    color: '#FFFFFF',
    fontSize: FONT_SIZES.small,
    marginHorizontal: 2,
  },
  sunCard: {
    margin: SPACING.md,
    padding: SPACING.md,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
  },
  sunCardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
    marginBottom: SPACING.sm,
  },
  sunCardTitle: {
    flex: 1,
    fontSize: FONT_SIZES.h4,
    fontWeight: '700',
  },
  sunTotalBadge: {
    color: '#FFFFFF',
    fontSize: FONT_SIZES.caption,
    fontWeight: '700',
    paddingHorizontal: SPACING.sm,
    paddingVertical: 4,
    borderRadius: RADIUS.pill,
    overflow: 'hidden',
  },
  sunRanges: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: SPACING.xs,
  },
  sunRange: {
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.sm,
    borderRadius: RADIUS.md,
  },
  sunRangeText: {
    fontSize: FONT_SIZES.small,
    fontWeight: '600',
  },
  sunNoneText: {
    fontSize: FONT_SIZES.small,
    lineHeight: 20,
    flex: 1,
  },
  noSunRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
  },
  sunDurationLine: {
    fontSize: FONT_SIZES.body,
    fontWeight: '700',
    marginBottom: SPACING.sm,
  },
  currentBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: SPACING.sm,
    paddingHorizontal: SPACING.sm + 2,
    paddingVertical: 6,
    borderRadius: RADIUS.pill,
    alignSelf: 'flex-start',
  },
  currentBannerText: {
    color: '#FFFFFF',
    fontSize: FONT_SIZES.caption,
    fontWeight: '700',
  },
  section: {
    marginHorizontal: SPACING.md,
    marginBottom: SPACING.md,
    padding: SPACING.md,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
    marginBottom: SPACING.sm,
  },
  sectionTitle: {
    fontSize: FONT_SIZES.h4,
    fontWeight: '700',
  },
  sliderRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  timeDisplay: {
    fontSize: FONT_SIZES.h3,
    fontWeight: '700',
  },
  resetBtn: {
    paddingHorizontal: SPACING.sm + 2,
    paddingVertical: 4,
    borderRadius: RADIUS.pill,
  },
  resetText: {
    fontSize: FONT_SIZES.caption,
    fontWeight: '700',
  },
  sliderLabels: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  sliderLabel: {
    fontSize: FONT_SIZES.caption,
    fontWeight: '500',
  },
  hourlySection: {
    marginBottom: SPACING.md,
  },
  hourCard: {
    width: 60,
    paddingVertical: SPACING.sm + 2,
    borderRadius: RADIUS.md,
    alignItems: 'center',
    gap: 4,
  },
  hourLabel: {
    fontSize: FONT_SIZES.caption,
    fontWeight: '700',
  },
  hourAlt: {
    fontSize: 10,
    fontWeight: '600',
  },
  descriptionText: {
    fontSize: FONT_SIZES.body,
    lineHeight: 24,
    fontWeight: '400',
  },
  generatingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
  },
  generatingText: {
    fontSize: FONT_SIZES.body,
  },
  infoGrid: {
    flexDirection: 'row',
    paddingHorizontal: SPACING.md,
    gap: SPACING.sm,
    marginBottom: SPACING.md,
  },
  infoCard: {
    flex: 1,
    padding: SPACING.md,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    alignItems: 'flex-start',
  },
  infoLabel: {
    fontSize: FONT_SIZES.caption,
    fontWeight: '500',
    marginTop: SPACING.xs,
  },
  infoValue: {
    fontSize: FONT_SIZES.body,
    fontWeight: '700',
    marginTop: 2,
  },
  infoSub: {
    fontSize: FONT_SIZES.caption,
    fontWeight: '400',
  },
  ctaBar: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: SPACING.md,
    paddingTop: SPACING.sm,
    borderTopWidth: 1,
  },
  ctaPrimary: {
    flex: 1,
    height: 52,
    borderRadius: RADIUS.lg,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  ctaPrimaryText: {
    color: '#FFFFFF',
    fontSize: FONT_SIZES.body,
    fontWeight: '700',
    letterSpacing: -0.2,
  },
  ctaSecondary: {
    width: 52,
    height: 52,
    borderRadius: RADIUS.lg,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
  },
  hoursList: {
    marginTop: SPACING.xs,
    gap: 3,
  },
  hoursLine: {
    fontSize: 12,
    lineHeight: 18,
  },
  infoRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginTop: SPACING.sm,
    paddingVertical: 6,
  },
  infoText: {
    fontSize: 13,
    fontWeight: '600',
    flex: 1,
    letterSpacing: -0.1,
  },
  pricePill: {
    marginLeft: 'auto',
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderRadius: 999,
  },
  pricePillText: {
    fontSize: 12,
    fontWeight: '800',
    letterSpacing: 1,
  },
  /* Share card — 1080x1080 offscreen template */
  shareCardWrapper: {
    position: 'absolute',
    left: -9999,
    top: 0,
    opacity: 0,
  },
  shareCard: {
    width: 1080,
    height: 1080,
    overflow: 'hidden',
    position: 'relative',
  },
  shareCardSunWrap: {
    position: 'absolute',
    top: -120,
    right: -120,
    width: 560,
    height: 560,
    borderRadius: 280,
    alignItems: 'center',
    justifyContent: 'center',
  },
  shareCardSun: {
    width: 480,
    height: 480,
    borderRadius: 240,
    backgroundColor: '#FFD580',
    opacity: 0.55,
  },
  shareCardContent: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    padding: 90,
    justifyContent: 'flex-end',
  },
  shareCardLogo: {
    position: 'absolute',
    top: 90,
    left: 90,
    fontSize: 64,
    fontWeight: '800',
    color: '#111111',
    fontStyle: 'italic',
    letterSpacing: -1.5,
  },
  shareCardKicker: {
    fontSize: 36,
    fontWeight: '700',
    color: '#111111',
    opacity: 0.75,
    marginBottom: 12,
    letterSpacing: -0.5,
  },
  shareCardName: {
    fontSize: 96,
    fontWeight: '900',
    color: '#111111',
    lineHeight: 102,
    letterSpacing: -3,
    marginBottom: 20,
  },
  shareCardCity: {
    fontSize: 40,
    fontWeight: '600',
    color: '#111111',
    opacity: 0.75,
    marginBottom: 40,
  },
  shareCardStatusPill: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    gap: 14,
    paddingVertical: 18,
    paddingHorizontal: 28,
    borderRadius: 999,
    backgroundColor: '#111111',
  },
  shareCardStatusDot: {
    width: 16,
    height: 16,
    borderRadius: 8,
    backgroundColor: '#F5A623',
  },
  shareCardStatusText: {
    fontSize: 32,
    fontWeight: '800',
    color: '#FFFFFF',
    letterSpacing: -0.5,
  },
  shareCardFoot: {
    position: 'absolute',
    bottom: 90,
    right: 90,
    fontSize: 26,
    fontWeight: '600',
    color: '#111111',
    opacity: 0.7,
  },
  communityHint: {
    fontSize: FONT_SIZES.small,
    marginBottom: SPACING.sm,
  },
  reportRow: {
    flexDirection: 'row',
    gap: 6,
    marginBottom: SPACING.sm,
  },
  reportPill: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
    paddingVertical: 10,
    paddingHorizontal: 8,
    borderRadius: RADIUS.pill,
    borderWidth: 1,
  },
  reportPillText: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: -0.2,
  },
  reportThanks: {
    fontSize: FONT_SIZES.caption,
    fontWeight: '700',
    marginTop: 2,
    marginBottom: SPACING.sm,
  },
  photoUploadBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    height: 46,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    marginTop: SPACING.sm,
  },
  photoUploadText: {
    fontSize: FONT_SIZES.small,
    fontWeight: '600',
  },
  shadowBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.md,
    marginHorizontal: SPACING.md,
    marginBottom: SPACING.md,
    paddingVertical: SPACING.sm + 2,
    paddingHorizontal: SPACING.md,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
  },
  shadowBadgeIcon: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  shadowBadgeTitle: {
    fontSize: 14,
    fontWeight: '800',
    letterSpacing: -0.2,
  },
  shadowBadgeSub: {
    fontSize: 11,
    fontWeight: '500',
    marginTop: 1,
    lineHeight: 15,
  },
  shadowBadgeChip: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 999,
  },
  shadowBadgeChipText: {
    color: '#FFFFFF',
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 0.4,
  },
});
