/**
 * Soleia - Soumettre une nouvelle terrasse.
 * Accessible via le FAB '+' de la carte.
 */
import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  ScrollView,
  Alert,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter, useLocalSearchParams } from 'expo-router';
import * as Location from 'expo-location';
import * as ImagePicker from 'expo-image-picker';
import { api } from '../src/api';
import { useTheme } from '../src/ThemeContext';
import { SPACING, RADIUS } from '../src/theme';

const TYPES = [
  { key: 'bar', label: 'Bar', icon: 'wine' },
  { key: 'cafe', label: 'Café', icon: 'cafe' },
  { key: 'restaurant', label: 'Restaurant', icon: 'restaurant' },
  { key: 'rooftop', label: 'Rooftop', icon: 'business' },
] as const;

const ORIENTATIONS = [
  { key: 'nord', label: 'Nord', deg: 0 },
  { key: 'est', label: 'Est', deg: 90 },
  { key: 'sud', label: 'Plein sud', deg: 180 },
  { key: 'ouest', label: 'Ouest', deg: 270 },
] as const;

export default function AddTerrace() {
  const router = useRouter();
  const { theme } = useTheme();
  const insets = useSafeAreaInsets();
  const params = useLocalSearchParams<{ city?: string }>();

  const [name, setName] = useState('');
  const [type, setType] = useState<string>('bar');
  const [orientation, setOrientation] = useState<string>('sud');
  const [photoBase64, setPhotoBase64] = useState<string | null>(null);
  const [coords, setCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    (async () => {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status === 'granted') {
        const loc = await Location.getCurrentPositionAsync({});
        setCoords({ lat: loc.coords.latitude, lng: loc.coords.longitude });
      } else {
        // fallback : centre de la ville
        setCoords({ lat: 47.2184, lng: -1.5536 });
      }
    })();
  }, []);

  const pickPhoto = async () => {
    const r = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      base64: true,
      quality: 0.5,
      allowsEditing: true,
      aspect: [4, 3],
    });
    if (!r.canceled && r.assets[0]?.base64) {
      setPhotoBase64(r.assets[0].base64);
    }
  };

  const submit = async () => {
    if (!name.trim()) {
      Alert.alert('Nom requis', "Donne un nom à la terrasse.");
      return;
    }
    if (!coords) {
      Alert.alert('Position', 'Position GPS indisponible.');
      return;
    }
    setSubmitting(true);
    try {
      await api.submitTerrace({
        name: name.trim(),
        type,
        orientation_label: orientation,
        lat: coords.lat,
        lng: coords.lng,
        city: params.city || 'Nantes',
        photo_base64: photoBase64 || undefined,
      });
      Alert.alert('Merci !', 'Ta terrasse a été ajoutée.', [
        { text: 'OK', onPress: () => router.back() },
      ]);
    } catch (e) {
      Alert.alert('Erreur', String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <View style={[styles.container, { backgroundColor: theme.background, paddingTop: insets.top }]}>
      <View style={[styles.header, { borderBottomColor: theme.border }]}>
        <TouchableOpacity onPress={() => router.back()} style={styles.closeBtn}>
          <Ionicons name="close" size={24} color={theme.text} />
        </TouchableOpacity>
        <Text style={[styles.title, { color: theme.text }]}>Ajouter une terrasse</Text>
        <View style={{ width: 40 }} />
      </View>

      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={{ flex: 1 }}
      >
        <ScrollView contentContainerStyle={{ padding: SPACING.md }} keyboardShouldPersistTaps="handled">
          <Text style={[styles.label, { color: theme.text }]}>Nom de l'établissement</Text>
          <TextInput
            style={[styles.input, { backgroundColor: theme.surface, color: theme.text, borderColor: theme.border }]}
            value={name}
            onChangeText={setName}
            placeholder="Ex. Le Petit Bar"
            placeholderTextColor={theme.textTertiary}
            testID="input-name"
          />

          <Text style={[styles.label, { color: theme.text, marginTop: SPACING.md }]}>Type</Text>
          <View style={styles.row}>
            {TYPES.map((t) => {
              const active = t.key === type;
              return (
                <TouchableOpacity
                  key={t.key}
                  onPress={() => setType(t.key)}
                  style={[
                    styles.chip,
                    {
                      backgroundColor: active ? theme.primary : theme.surface,
                      borderColor: active ? theme.primary : theme.border,
                    },
                  ]}
                  testID={`type-${t.key}`}
                >
                  <Text style={[styles.chipText, { color: active ? '#FFF' : theme.text }]}>
                    {t.label}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>

          <Text style={[styles.label, { color: theme.text, marginTop: SPACING.md }]}>Orientation</Text>
          <View style={styles.row}>
            {ORIENTATIONS.map((o) => {
              const active = o.key === orientation;
              return (
                <TouchableOpacity
                  key={o.key}
                  onPress={() => setOrientation(o.key)}
                  style={[
                    styles.chip,
                    {
                      backgroundColor: active ? theme.primary : theme.surface,
                      borderColor: active ? theme.primary : theme.border,
                    },
                  ]}
                  testID={`orient-${o.key}`}
                >
                  <Text style={[styles.chipText, { color: active ? '#FFF' : theme.text }]}>
                    {o.label}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>

          <Text style={[styles.label, { color: theme.text, marginTop: SPACING.md }]}>Photo (optionnel)</Text>
          <TouchableOpacity
            onPress={pickPhoto}
            style={[styles.photoBtn, { borderColor: theme.border, backgroundColor: theme.surface }]}
            testID="pick-photo"
          >
            <Ionicons name={photoBase64 ? 'checkmark-circle' : 'image-outline'} size={22} color={theme.primary} />
            <Text style={[styles.photoBtnText, { color: theme.text }]}>
              {photoBase64 ? 'Photo sélectionnée' : 'Choisir une photo'}
            </Text>
          </TouchableOpacity>

          <View style={{ marginTop: SPACING.md }}>
            <Text style={[styles.hint, { color: theme.textTertiary }]}>
              Position utilisée : {coords ? `${coords.lat.toFixed(4)}, ${coords.lng.toFixed(4)}` : '...'}
            </Text>
            <Text style={[styles.hint, { color: theme.textTertiary }]}>
              Ville : {params.city || 'Nantes'}
            </Text>
          </View>
        </ScrollView>

        <TouchableOpacity
          onPress={submit}
          disabled={submitting}
          style={[
            styles.submitBtn,
            {
              backgroundColor: theme.primary,
              marginBottom: Math.max(SPACING.md, insets.bottom),
              opacity: submitting ? 0.7 : 1,
            },
          ]}
          testID="submit-terrace"
        >
          {submitting ? (
            <ActivityIndicator color="#FFF" />
          ) : (
            <Text style={styles.submitBtnText}>Ajouter la terrasse</Text>
          )}
        </TouchableOpacity>
      </KeyboardAvoidingView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  closeBtn: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 17, fontWeight: '700' },
  label: { fontSize: 13, fontWeight: '700', marginBottom: 6, letterSpacing: 0.2 },
  input: {
    height: 48,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    paddingHorizontal: SPACING.sm,
    fontSize: 15,
  },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: {
    paddingHorizontal: 14,
    paddingVertical: 9,
    borderRadius: 999,
    borderWidth: 1,
  },
  chipText: { fontSize: 13, fontWeight: '600' },
  photoBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    height: 48,
    paddingHorizontal: SPACING.md,
    borderRadius: RADIUS.md,
    borderWidth: 1,
  },
  photoBtnText: { fontSize: 14, fontWeight: '500' },
  hint: { fontSize: 11, marginBottom: 2 },
  submitBtn: {
    height: 52,
    marginHorizontal: SPACING.md,
    borderRadius: RADIUS.lg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  submitBtnText: { color: '#FFF', fontSize: 16, fontWeight: '700' },
});
