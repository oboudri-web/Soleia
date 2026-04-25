/**
 * Soleia - Logo component (sunrise mark + Fraunces italic wordmark)
 *
 * Composition:
 *  - Sunrise arc (half-dome + 5 rays) in orange #F5A623
 *  - "Soleia" wordmark in Fraunces 700 Italic right next to the mark
 *
 * Same props as before for backwards compatibility. The `size` prop
 * controls the wordmark font-size; the mark scales accordingly.
 */
import React from 'react';
import { View } from 'react-native';
import Svg, { Path, Line, G } from 'react-native-svg';
import { Text } from 'react-native';

type Props = {
  size?: number;
  accentColor?: string;
  textColor?: string;
  /** If true, render only the sunrise mark (no wordmark) - for tight headers/splash. */
  markOnly?: boolean;
};

function SunriseMark({ size, color }: { size: number; color: string }) {
  // Viewbox 120x72: half-dome + 5 rays above, ground line below.
  const w = size;
  const h = size * 0.6;
  return (
    <Svg width={w} height={h} viewBox="0 0 120 72">
      <G>
        {/* Dome (half-circle) */}
        <Path
          d="M 20 58 A 40 40 0 0 1 100 58"
          fill={color}
        />
        {/* Rays - 5 short strokes above the dome */}
        {[
          { x1: 60, y1: 4,  x2: 60, y2: 14 },
          { x1: 30, y1: 16, x2: 36, y2: 24 },
          { x1: 90, y1: 16, x2: 84, y2: 24 },
          { x1: 10, y1: 38, x2: 20, y2: 38 },
          { x1: 110, y1: 38, x2: 100, y2: 38 },
        ].map((r, i) => (
          <Line
            key={i}
            x1={r.x1}
            y1={r.y1}
            x2={r.x2}
            y2={r.y2}
            stroke={color}
            strokeWidth="5"
            strokeLinecap="round"
          />
        ))}
        {/* Ground line */}
        <Line
          x1="8"
          y1="62"
          x2="112"
          y2="62"
          stroke={color}
          strokeWidth="4"
          strokeLinecap="round"
        />
      </G>
    </Svg>
  );
}

export default function SoleiaLogo({
  size = 32,
  accentColor = '#F5A623',
  textColor = '#111111',
  markOnly = false,
}: Props) {
  const markSize = Math.round(size * 1.15);
  const baseStyle = {
    fontFamily: 'Fraunces_700Bold_Italic' as const,
    fontSize: size,
    letterSpacing: -1,
    lineHeight: size * 1.1,
    color: textColor,
  };
  if (markOnly) {
    return <SunriseMark size={markSize} color={accentColor} />;
  }
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: Math.round(size * 0.22) }}>
      <SunriseMark size={markSize} color={accentColor} />
      <Text style={baseStyle}>Soleia</Text>
    </View>
  );
}
