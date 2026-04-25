/**
 * Soleia - Onboarding (single screen, final)
 * - White editorial design with a minimal SVG sun illustration.
 * - One primary CTA: request GPS permission + mark done + enter the map.
 * - Secondary "Passer": skip GPS but still mark done.
 * - Shown only once thanks to AsyncStorage (@soleia/onboarding_done_v1).
 */
import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  Platform,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import * as Location from 'expo-location';
import Svg, { Circle, Line, Rect, G, Ellipse, Path } from 'react-native-svg';

import SoleiaLogo from '../src/components/SoleiaLogo';
import { SPACING } from '../src/theme';
import { setOnboardingDone } from '../src/utils/appState';

function SunIllustration() {
  // "Terrasse vue de face" : table ronde + 2 chaises + verre, soleil au-dessus.
  // Noir #111 pour tout le mobilier, jaune #F5A623 uniquement pour le soleil.
  const sunCx = 140;
  const sunCy = 40;
  const sunR = 20;
  return (
    <View style={{ alignItems: 'center', marginVertical: 24 }}>
      <Svg width={280} height={210} viewBox="0 0 280 210">
        {/* Soleil */}
        <Circle cx={sunCx} cy={sunCy} r={sunR} fill="#F5A623" />
        {[0, 45, 90, 135, 180, 225, 270, 315].map((angle) => {
          const rad = (angle * Math.PI) / 180;
          const x1 = sunCx + Math.cos(rad) * (sunR + 8);
          const y1 = sunCy + Math.sin(rad) * (sunR + 8);
          const x2 = sunCx + Math.cos(rad) * (sunR + 19);
          const y2 = sunCy + Math.sin(rad) * (sunR + 19);
          return (
            <Line
              key={angle}
              x1={x1}
              y1={y1}
              x2={x2}
              y2={y2}
              stroke="#F5A623"
              strokeWidth="3.5"
              strokeLinecap="round"
            />
          );
        })}

        {/* Chaise gauche (silhouette bistro : dossier + assise + 2 pieds) */}
        <G stroke="#111" strokeWidth="3" strokeLinecap="round" fill="none">
          <Line x1="52" y1="105" x2="52" y2="145" />
          <Line x1="45" y1="145" x2="88" y2="145" />
          <Line x1="50" y1="145" x2="50" y2="185" />
          <Line x1="85" y1="145" x2="85" y2="185" />
        </G>

        {/* Chaise droite (miroir) */}
        <G stroke="#111" strokeWidth="3" strokeLinecap="round" fill="none">
          <Line x1="228" y1="105" x2="228" y2="145" />
          <Line x1="192" y1="145" x2="235" y2="145" />
          <Line x1="195" y1="145" x2="195" y2="185" />
          <Line x1="230" y1="145" x2="230" y2="185" />
        </G>

        {/* Table ronde vue de face : plateau elliptique + pied central + base */}
        <G>
          <Ellipse cx="140" cy="135" rx="48" ry="7" fill="#111" />
          <Rect x="136" y="135" width="8" height="42" fill="#111" />
          <Ellipse cx="140" cy="180" rx="22" ry="4.5" fill="#111" />
        </G>

        {/* Verre posé sur la table (tumbler outline, légèrement évasé vers le haut) */}
        <Path
          d="M 132 128 L 130 104 L 150 104 L 148 128 Z"
          stroke="#111"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="#FFFFFF"
        />
        {/* petit ovale d'ouverture du verre */}
        <Ellipse cx="140" cy="104" rx="10" ry="2" fill="#FFFFFF" stroke="#111" strokeWidth="2" />

        {/* Sol */}
        <Line x1="14" y1="196" x2="266" y2="196" stroke="#111" strokeWidth="2" strokeLinecap="round" />
      </Svg>
    </View>
  );
}

export default function Onboarding() {
  const router = useRouter();
  const [requesting, setRequesting] = useState(false);

  const goToMap = () => router.replace({ pathname: '/map', params: { city: 'Nantes' } });

  const handleStart = async () => {
    if (requesting) return;
    setRequesting(true);
    try {
      await Location.requestForegroundPermissionsAsync();
    } catch {
      // ignore permission errors — we still continue
    } finally {
      await setOnboardingDone();
      setRequesting(false);
      goToMap();
    }
  };

  const handleSkip = async () => {
    await setOnboardingDone();
    goToMap();
  };

  return (
    <SafeAreaView style={styles.container} edges={['top', 'bottom']}>
      <View style={styles.topBar}>
        <SoleiaLogo size={22} textColor="#111" />
      </View>

      <View style={styles.content}>
        <SunIllustration />

        <Text style={styles.title} testID="onboarding-title">
          Fini les terrasses{'\n'}à l'ombre
        </Text>
        <Text style={styles.subtitle}>
          Soleia trouve en temps réel les terrasses{'\n'}ensoleillées autour de toi.
        </Text>
      </View>

      <View style={styles.bottom}>
        <TouchableOpacity
          testID="onboarding-start"
          activeOpacity={0.88}
          onPress={handleStart}
          disabled={requesting}
          style={styles.primaryBtn}
        >
          {requesting ? (
            <ActivityIndicator size="small" color="#FFF" />
          ) : (
            <Ionicons name="location" size={16} color="#FFF" />
          )}
          <Text style={styles.primaryText}>
            {requesting ? 'Demande en cours...' : 'Activer ma position et commencer'}
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          testID="onboarding-skip"
          activeOpacity={0.7}
          onPress={handleSkip}
          style={styles.skipBtn}
        >
          <Text style={styles.skipText}>Passer</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#FFFFFF',
  },
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: SPACING.md,
    paddingTop: SPACING.sm,
    paddingBottom: SPACING.xs,
  },
  content: {
    flex: 1,
    paddingHorizontal: SPACING.lg,
    justifyContent: 'center',
    alignItems: 'center',
  },
  title: {
    fontSize: 36,
    fontWeight: '800',
    color: '#111',
    textAlign: 'center',
    letterSpacing: -1.2,
    lineHeight: 42,
    marginBottom: 14,
  },
  subtitle: {
    fontSize: 16,
    color: '#666',
    textAlign: 'center',
    lineHeight: 22,
    fontWeight: '400',
  },
  bottom: {
    paddingHorizontal: SPACING.lg,
    paddingBottom: SPACING.md,
    paddingTop: SPACING.sm,
    gap: 6,
  },
  primaryBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    height: 56,
    borderRadius: 16,
    backgroundColor: '#111',
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 6 },
        shadowOpacity: 0.15,
        shadowRadius: 14,
      },
      android: { elevation: 3 },
    }),
  },
  primaryText: {
    color: '#FFF',
    fontSize: 16,
    fontWeight: '700',
    letterSpacing: -0.2,
  },
  skipBtn: {
    alignSelf: 'center',
    paddingVertical: 12,
    paddingHorizontal: 24,
  },
  skipText: {
    color: '#AAA',
    fontSize: 14,
    fontWeight: '600',
  },
});
