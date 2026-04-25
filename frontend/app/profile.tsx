/**
 * Soleia - Profile screen (local favorites only).
 *
 * Google Sign-In has been removed. This screen just displays the count of
 * favorites stored on-device.
 */
import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, ActivityIndicator } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useTheme } from '../src/ThemeContext';
import { useAuth } from '../src/AuthContext';

export default function ProfileScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { theme, isDark } = useTheme();
  const { favoriteIds, ready } = useAuth();

  return (
    <View style={[styles.container, { backgroundColor: theme.background, paddingTop: insets.top }]}>
      {/* Header */}
      <View style={[styles.header, { borderBottomColor: theme.border }]}>
        <TouchableOpacity
          onPress={() => router.back()}
          style={styles.closeBtn}
          hitSlop={8}
          accessibilityLabel="Fermer"
        >
          <Ionicons name="close" size={26} color={theme.text} />
        </TouchableOpacity>
        <Text style={[styles.headerTitle, { color: theme.text }]}>Mon compte</Text>
        <View style={{ width: 32 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 40 }}>
        {!ready ? (
          <View style={{ paddingVertical: 40, alignItems: 'center' }}>
            <ActivityIndicator color={theme.primary} />
          </View>
        ) : (
          <>
            {/* Hero */}
            <View style={{ alignItems: 'center', marginTop: 16, marginBottom: 24 }}>
              <View style={[styles.heroIcon, { backgroundColor: isDark ? '#1a1a1a' : '#FFF3E0' }]}>
                <Ionicons name="sunny" size={56} color="#F5A623" />
              </View>
              <Text style={[styles.heroTitle, { color: theme.text }]}>Bienvenue sur Soleia</Text>
              <Text style={[styles.heroSubtitle, { color: theme.textSecondary }]}>
                Tes favoris sont sauvegardés sur cet appareil.
              </Text>
            </View>

            {/* Favorites card */}
            <View style={[styles.card, { backgroundColor: theme.surface, borderColor: theme.border }]}>
              <View style={styles.statRow}>
                <Ionicons name="heart" size={22} color="#E85D75" />
                <Text style={[styles.statLabel, { color: theme.text }]}>Terrasses favorites</Text>
                <Text style={[styles.statValue, { color: theme.text }]}>{favoriteIds.length}</Text>
              </View>
              <View style={[styles.separator, { backgroundColor: theme.border }]} />
              <View style={styles.infoRow}>
                <Ionicons name="phone-portrait-outline" size={20} color={theme.primary} />
                <Text style={[styles.infoText, { color: theme.textSecondary }]}>
                  Les favoris sont stockés localement sur ton téléphone.
                </Text>
              </View>
            </View>

            {/* About */}
            <View style={[styles.card, { backgroundColor: theme.surface, borderColor: theme.border, marginTop: 14 }]}>
              <BulletItem theme={theme} icon="sunny-outline" text="Trouve les terrasses au soleil en temps réel" />
              <BulletItem theme={theme} icon="map-outline" text="Carte interactive avec ombres 3D" />
              <BulletItem theme={theme} icon="time-outline" text="Planifie jusqu'à 7 jours à l'avance" />
            </View>
          </>
        )}
      </ScrollView>
    </View>
  );
}

function BulletItem({ theme, icon, text }: { theme: any; icon: any; text: string }) {
  return (
    <View style={styles.bulletRow}>
      <Ionicons name={icon} size={20} color={theme.primary} />
      <Text style={[styles.bulletText, { color: theme.text }]}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderBottomWidth: 1,
  },
  closeBtn: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center' },
  headerTitle: { fontSize: 17, fontWeight: '600' },
  card: { borderRadius: 14, borderWidth: 1, padding: 16 },
  statRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  statLabel: { flex: 1, fontSize: 15, fontWeight: '500' },
  statValue: { fontSize: 17, fontWeight: '700' },
  separator: { height: 1, marginVertical: 14 },
  infoRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  infoText: { flex: 1, fontSize: 13, lineHeight: 18 },
  heroIcon: {
    width: 120,
    height: 120,
    borderRadius: 60,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 18,
  },
  heroTitle: { fontSize: 22, fontWeight: '700', textAlign: 'center', marginBottom: 8 },
  heroSubtitle: { fontSize: 15, textAlign: 'center', lineHeight: 21, paddingHorizontal: 20 },
  bulletRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 8 },
  bulletText: { flex: 1, fontSize: 14, lineHeight: 20 },
});
