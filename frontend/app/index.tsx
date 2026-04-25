/**
 * Soleia - Splash Screen avec logo Fraunces
 */
import React, { useEffect, useRef } from 'react';
import { View, StyleSheet, Animated, Easing } from 'react-native';
import { useRouter } from 'expo-router';
import SoleiaLogo from '../src/components/SoleiaLogo';
import { isOnboardingDone } from '../src/utils/appState';

export default function Index() {
  const router = useRouter();
  const sunScale = useRef(new Animated.Value(0)).current;
  const sunRotate = useRef(new Animated.Value(0)).current;
  const logoOpacity = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.sequence([
      Animated.parallel([
        Animated.spring(sunScale, {
          toValue: 1,
          tension: 40,
          friction: 6,
          useNativeDriver: true,
        }),
        Animated.loop(
          Animated.timing(sunRotate, {
            toValue: 1,
            duration: 20000,
            easing: Easing.linear,
            useNativeDriver: true,
          })
        ),
      ]),
      Animated.timing(logoOpacity, {
        toValue: 1,
        duration: 500,
        useNativeDriver: true,
      }),
    ]).start();

    const timer = setTimeout(async () => {
      try {
        const done = await isOnboardingDone();
        router.replace(done ? { pathname: '/map', params: { city: 'Nantes' } } : '/onboarding');
      } catch {
        router.replace('/onboarding');
      }
    }, 1800);
    return () => clearTimeout(timer);
  }, [router, sunScale, sunRotate, logoOpacity]);

  const spin = sunRotate.interpolate({
    inputRange: [0, 1],
    outputRange: ['0deg', '360deg'],
  });

  const rays = Array.from({ length: 12 }, (_, i) => {
    const angle = (i * 30) * Math.PI / 180;
    return (
      <View
        key={i}
        style={{
          position: 'absolute',
          width: 6,
          height: 24,
          backgroundColor: '#F5A623',
          borderRadius: 3,
          transform: [
            { translateX: Math.cos(angle) * 100 },
            { translateY: Math.sin(angle) * 100 },
            { rotate: `${i * 30 + 90}deg` },
          ],
        }}
      />
    );
  });

  return (
    <View style={styles.container} testID="splash-screen">
      <Animated.View
        style={[
          styles.sunWrap,
          {
            transform: [{ scale: sunScale }, { rotate: spin }],
          },
        ]}
      >
        <View style={styles.sunCore} />
        {rays}
      </Animated.View>

      <Animated.View style={[styles.logoWrap, { opacity: logoOpacity }]}>
        <SoleiaLogo size={40} />
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#FFFFFF',
    alignItems: 'center',
    justifyContent: 'center',
  },
  sunWrap: {
    position: 'absolute',
    width: 180,
    height: 180,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sunCore: {
    width: 100,
    height: 100,
    borderRadius: 50,
    backgroundColor: '#F5A623',
  },
  logoWrap: {
    zIndex: 10,
  },
});
