/**
 * Soleia - Page restaurateur "Soleia Pro".
 * Landing + formulaire de contact.
 */
import React, { useState } from 'react';
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
  Linking,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { api } from '../src/api';
import { useTheme } from '../src/ThemeContext';
import SoleiaLogo from '../src/components/SoleiaLogo';
import { SPACING, RADIUS } from '../src/theme';

const FEATURES = [
  { icon: 'sunny', text: 'Votre terrasse mise en avant' },
  { icon: 'ribbon', text: 'Badge "Partenaire Soleia"' },
  { icon: 'stats-chart', text: 'Stats de visibilité mensuelles' },
  { icon: 'checkmark-circle', text: 'Orientation vérifiée par notre équipe' },
];

export default function ProPage() {
  const router = useRouter();
  const { theme } = useTheme();
  const insets = useSafeAreaInsets();

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [city, setCity] = useState('');
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);

  const submit = async () => {
    if (!name.trim() || !email.includes('@') || !city.trim()) {
      Alert.alert('Champs manquants', 'Remplis au moins nom, email valide et ville.');
      return;
    }
    setSending(true);
    try {
      await api.proContact({
        establishment_name: name.trim(),
        email: email.trim(),
        city: city.trim(),
        message: message.trim() || undefined,
      });
      Alert.alert('Merci !', "On revient vers toi dans les plus brefs délais.", [
        { text: 'OK', onPress: () => router.back() },
      ]);
    } catch (e) {
      Alert.alert('Erreur', String(e));
    } finally {
      setSending(false);
    }
  };

  return (
    <View style={[styles.container, { backgroundColor: theme.background, paddingTop: insets.top }]}>
      <View style={[styles.header, { borderBottomColor: theme.border }]}>
        <TouchableOpacity onPress={() => router.back()} style={styles.closeBtn}>
          <Ionicons name="close" size={24} color={theme.text} />
        </TouchableOpacity>
        <Text style={[styles.title, { color: theme.text }]}>Soleia Pro</Text>
        <View style={{ width: 40 }} />
      </View>

      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={{ flex: 1 }}
      >
        <ScrollView contentContainerStyle={{ padding: SPACING.md, paddingBottom: 40 }} keyboardShouldPersistTaps="handled">
          <View style={{ alignItems: 'center', marginTop: SPACING.md }}>
            <SoleiaLogo size={36} textColor={theme.text} />
          </View>

          <Text style={[styles.hero, { color: theme.text }]}>
            Votre terrasse mérite{'\n'}d'être trouvée 🌞
          </Text>
          <Text style={[styles.subhero, { color: theme.textSecondary }]}>
            Rejoignez Soleia Pro et soyez visible par des milliers de personnes
            qui cherchent une terrasse au soleil près de chez eux.
          </Text>

          <View style={styles.features}>
            {FEATURES.map((f) => (
              <View key={f.icon} style={styles.feature}>
                <Ionicons name={f.icon as any} size={18} color={theme.primary} />
                <Text style={[styles.featureText, { color: theme.text }]}>{f.text}</Text>
              </View>
            ))}
          </View>

          <TouchableOpacity
            onPress={() => Linking.openURL('mailto:contact@soleia.fr')}
            style={[styles.emailBtn, { borderColor: theme.border }]}
          >
            <Ionicons name="mail" size={16} color={theme.primary} />
            <Text style={[styles.emailBtnText, { color: theme.text }]}>contact@soleia.fr</Text>
          </TouchableOpacity>

          <Text style={[styles.formTitle, { color: theme.text }]}>
            Ou remplissez ce formulaire
          </Text>

          <Text style={[styles.label, { color: theme.text }]}>Nom de l'établissement</Text>
          <TextInput
            style={[styles.input, { backgroundColor: theme.surface, color: theme.text, borderColor: theme.border }]}
            value={name}
            onChangeText={setName}
            placeholder="Ex. Café du Soleil"
            placeholderTextColor={theme.textTertiary}
            testID="pro-name"
          />
          <Text style={[styles.label, { color: theme.text }]}>Votre email</Text>
          <TextInput
            style={[styles.input, { backgroundColor: theme.surface, color: theme.text, borderColor: theme.border }]}
            value={email}
            onChangeText={setEmail}
            placeholder="vous@exemple.fr"
            placeholderTextColor={theme.textTertiary}
            keyboardType="email-address"
            autoCapitalize="none"
            testID="pro-email"
          />
          <Text style={[styles.label, { color: theme.text }]}>Ville</Text>
          <TextInput
            style={[styles.input, { backgroundColor: theme.surface, color: theme.text, borderColor: theme.border }]}
            value={city}
            onChangeText={setCity}
            placeholder="Ex. Nantes"
            placeholderTextColor={theme.textTertiary}
            testID="pro-city"
          />
          <Text style={[styles.label, { color: theme.text }]}>Message (optionnel)</Text>
          <TextInput
            style={[styles.inputMulti, { backgroundColor: theme.surface, color: theme.text, borderColor: theme.border }]}
            value={message}
            onChangeText={setMessage}
            placeholder="Quelques mots sur votre terrasse..."
            placeholderTextColor={theme.textTertiary}
            multiline
            numberOfLines={4}
            testID="pro-message"
          />
        </ScrollView>

        <TouchableOpacity
          onPress={submit}
          disabled={sending}
          style={[styles.sendBtn, {
            backgroundColor: theme.primary,
            marginBottom: Math.max(SPACING.md, insets.bottom),
            opacity: sending ? 0.7 : 1,
          }]}
          testID="pro-submit"
        >
          {sending ? <ActivityIndicator color="#FFF" /> : (
            <Text style={styles.sendBtnText}>Envoyer ma demande</Text>
          )}
        </TouchableOpacity>
      </KeyboardAvoidingView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: SPACING.md, paddingVertical: SPACING.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  closeBtn: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 17, fontWeight: '700' },
  hero: {
    fontSize: 26, fontWeight: '800', textAlign: 'center',
    marginTop: SPACING.lg, marginBottom: SPACING.sm, letterSpacing: -0.5,
  },
  subhero: {
    fontSize: 14, textAlign: 'center', lineHeight: 20,
    marginBottom: SPACING.lg, paddingHorizontal: SPACING.sm,
  },
  features: { gap: 12, marginBottom: SPACING.lg },
  feature: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  featureText: { fontSize: 14, fontWeight: '500' },
  emailBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
    borderWidth: 1, paddingVertical: 12, borderRadius: RADIUS.md,
    marginBottom: SPACING.lg,
  },
  emailBtnText: { fontSize: 14, fontWeight: '600' },
  formTitle: { fontSize: 15, fontWeight: '700', marginBottom: SPACING.sm },
  label: { fontSize: 12, fontWeight: '700', marginTop: 10, marginBottom: 4 },
  input: {
    height: 44, borderRadius: RADIUS.md, borderWidth: 1,
    paddingHorizontal: SPACING.sm, fontSize: 14,
  },
  inputMulti: {
    minHeight: 90, borderRadius: RADIUS.md, borderWidth: 1,
    padding: SPACING.sm, fontSize: 14, textAlignVertical: 'top',
  },
  sendBtn: {
    height: 52, marginHorizontal: SPACING.md, borderRadius: RADIUS.lg,
    alignItems: 'center', justifyContent: 'center',
  },
  sendBtnText: { color: '#FFF', fontSize: 16, fontWeight: '700' },
});
