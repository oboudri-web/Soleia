/**
 * Soleia - Marqueur carte minimaliste (point statique, aucune animation)
 *
 * CRITICAL: Ne JAMAIS utiliser Animated.View ou useEffect animation loops ici.
 * react-native-maps snapshot ce component en ImageMarker natif via
 * `tracksViewChanges={false}`. Toute animation en cours pendant un pan/zoom
 * peut crasher le thread natif Google Maps (SIGSEGV sans message JS).
 *
 * Les ombres au sol, halos, pulse : tout se fait côté carte via styling
 * statique uniquement.
 */
import React from 'react';
import { View, StyleSheet, TouchableOpacity, Platform } from 'react-native';
import type { SunStatus } from '../api';

type Props = {
  status: SunStatus;
  type?: string;
  onPress?: () => void;
  selected?: boolean;
  /** Si false → marqueur outline (non vérifié). Défaut true. */
  verified?: boolean;
};

function TerraceMarkerImpl({
  status,
  onPress,
  selected = false,
  verified = true,
}: Props) {
  const cfg =
    status === 'sunny'
      ? { color: '#F5A623', size: 20, border: 2.5 }
      : status === 'soon'
      ? { color: '#FF8C42', size: 16, border: 2 }
      : { color: '#BBBBBB', size: 14, border: 2 };

  const finalSize = selected ? cfg.size + 6 : cfg.size;

  const dot = (
    <View style={styles.container} pointerEvents={onPress ? 'auto' : 'none'}>
      {/* Selection ring (golden) */}
      {selected && (
        <View
          pointerEvents="none"
          style={[
            styles.pulse,
            {
              width: finalSize + 10,
              height: finalSize + 10,
              borderRadius: (finalSize + 10) / 2,
              borderWidth: 2,
              borderColor: '#F5A623',
            },
          ]}
        />
      )}
      {/* Subtle static shadow halo for shade markers */}
      {status === 'shade' && (
        <View
          pointerEvents="none"
          style={[
            styles.pulse,
            {
              width: finalSize + 12,
              height: finalSize + 12,
              borderRadius: (finalSize + 12) / 2,
              backgroundColor: '#000000',
              opacity: 0.1,
            },
          ]}
        />
      )}
      <View
        style={[
          styles.dot,
          {
            width: finalSize,
            height: finalSize,
            borderRadius: finalSize / 2,
            backgroundColor: verified ? cfg.color : 'rgba(255,255,255,0.92)',
            borderWidth: verified ? cfg.border : 2.5,
            borderColor: verified ? '#FFFFFF' : cfg.color,
          },
        ]}
      />
    </View>
  );

  if (onPress) {
    return (
      <TouchableOpacity activeOpacity={0.8} onPress={onPress} testID={`marker-${status}`}>
        {dot}
      </TouchableOpacity>
    );
  }
  return dot;
}

const styles = StyleSheet.create({
  container: {
    width: 44,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
  },
  pulse: {
    position: 'absolute',
  },
  dot: {
    borderColor: '#FFFFFF',
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 1 },
        shadowOpacity: 0.18,
        shadowRadius: 2,
      },
      android: {
        elevation: 3,
      },
      default: {
        boxShadow: '0 1px 3px rgba(0,0,0,0.18)',
      },
    }),
  },
});

const TerraceMarker = React.memo(TerraceMarkerImpl, (prev, next) => {
  return (
    prev.status === next.status &&
    prev.selected === next.selected &&
    prev.verified === next.verified &&
    prev.onPress === next.onPress
  );
});

export default TerraceMarker;
