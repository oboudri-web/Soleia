/**
 * Soleia - SearchBar (carte)
 * Recherche en temps réel avec debounce 200ms, dropdown de résultats.
 */
import React, { useState, useCallback, useEffect, useRef } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Keyboard,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { api, type Terrace } from '../api';
import { useTheme } from '../ThemeContext';
import { SPACING, RADIUS } from '../theme';

type Props = {
  city?: string;
  onSelect: (t: Terrace) => void;
};

const STATUS_COLOR: Record<string, string> = {
  sunny: '#F5A623',
  soon: '#FF8C42',
  shade: '#BDBDBD',
};
const STATUS_LABEL: Record<string, string> = {
  sunny: 'Au soleil',
  soon: 'Bientôt',
  shade: "À l'ombre",
};

export default function SearchBar({ city, onSelect }: Props) {
  const { theme } = useTheme();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Terrace[]>([]);
  const [loading, setLoading] = useState(false);
  const [focused, setFocused] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const doSearch = useCallback(
    async (text: string) => {
      if (text.trim().length < 2) {
        setResults([]);
        setLoading(false);
        return;
      }
      setLoading(true);
      try {
        const data = await api.searchTerraces(text.trim(), city);
        setResults(data.results || []);
      } catch (e) {
        setResults([]);
      } finally {
        setLoading(false);
      }
    },
    [city],
  );

  // Debounce 200ms
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => doSearch(query), 200);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [query, doSearch]);

  const clear = () => {
    setQuery('');
    setResults([]);
    Keyboard.dismiss();
  };

  const handleSelect = (t: Terrace) => {
    onSelect(t);
    setQuery('');
    setResults([]);
    Keyboard.dismiss();
  };

  const showDropdown = focused && query.trim().length >= 2;

  return (
    <View style={styles.wrapper}>
      <View
        style={[
          styles.bar,
          {
            backgroundColor: theme.surface,
            borderColor: theme.border,
          },
        ]}
      >
        <Ionicons name="search" size={16} color={theme.textTertiary} />
        <TextInput
          testID="search-input"
          value={query}
          onChangeText={setQuery}
          onFocus={() => setFocused(true)}
          onBlur={() => setTimeout(() => setFocused(false), 150)}
          placeholder="Rechercher une terrasse, un bar..."
          placeholderTextColor={theme.textTertiary}
          style={[styles.input, { color: theme.text }]}
          returnKeyType="search"
          autoCorrect={false}
          autoCapitalize="none"
        />
        {loading ? (
          <ActivityIndicator size="small" color={theme.textTertiary} />
        ) : query.length > 0 ? (
          <TouchableOpacity testID="search-clear" onPress={clear} hitSlop={{ top: 8, right: 8, bottom: 8, left: 8 }}>
            <Ionicons name="close-circle" size={16} color={theme.textTertiary} />
          </TouchableOpacity>
        ) : null}
      </View>

      {showDropdown && (
        <View
          style={[
            styles.dropdown,
            { backgroundColor: theme.surface, borderColor: theme.border },
          ]}
          testID="search-results"
        >
          {results.length === 0 && !loading ? (
            <View style={styles.empty}>
              <Text style={[styles.emptyText, { color: theme.textSecondary }]}>
                Aucun résultat pour « {query} »
              </Text>
            </View>
          ) : (
            results.map((t) => (
              <TouchableOpacity
                key={t.id}
                testID={`search-result-${t.id}`}
                activeOpacity={0.7}
                onPress={() => handleSelect(t)}
                style={[styles.item, { borderBottomColor: theme.border }]}
              >
                <View style={[styles.dot, { backgroundColor: STATUS_COLOR[t.sun_status] || '#BBB' }]} />
                <View style={{ flex: 1 }}>
                  <Text style={[styles.name, { color: theme.text }]} numberOfLines={1}>
                    {t.name}
                  </Text>
                  <Text style={[styles.sub, { color: theme.textSecondary }]} numberOfLines={1}>
                    {t.type === 'bar' ? 'Bar' : t.type === 'cafe' ? 'Café' : t.type === 'restaurant' ? 'Restaurant' : 'Rooftop'}
                    {' · '}
                    {t.city}
                  </Text>
                </View>
                <Text
                  style={[
                    styles.status,
                    { color: STATUS_COLOR[t.sun_status] || theme.textSecondary },
                  ]}
                >
                  {STATUS_LABEL[t.sun_status] || '—'}
                </Text>
              </TouchableOpacity>
            ))
          )}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    width: '100%',
  },
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    height: 44,
    paddingHorizontal: 12,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.08,
    shadowRadius: 8,
    elevation: 2,
  },
  input: {
    flex: 1,
    fontSize: 14,
    fontWeight: '500',
    paddingVertical: 0,
  },
  dropdown: {
    marginTop: 6,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    overflow: 'hidden',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.12,
    shadowRadius: 12,
    elevation: 5,
    maxHeight: 320,
  },
  empty: {
    padding: SPACING.md,
  },
  emptyText: {
    fontSize: 13,
    textAlign: 'center',
  },
  item: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  name: {
    fontSize: 14,
    fontWeight: '700',
    letterSpacing: -0.2,
  },
  sub: {
    fontSize: 11,
    fontWeight: '500',
    marginTop: 1,
  },
  status: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.2,
  },
});
