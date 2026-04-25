# Soleia - PRD

## Vision
App mobile premium (iOS + Android) "Soleia" — Trouve ta terrasse au soleil.
Calcul solaire précis en temps réel pour les terrasses françaises.

## Features MVP
1. **Moteur de calcul solaire** (pysolar) avec `at_time` optionnel sur tous les endpoints
2. **Splash animé** : fond blanc, "Soleia" noir bold + soleil jaune #F5A623 rotatif
3. **Onboarding 3 étapes** (Bienvenue, Ta ville, Ton ambiance)
4. **Écran Map** :
   - Carte avec markers colorés (jaune/orange/gris) + animations pulsantes
   - Bottom sheet avec liste terrasses
   - Filtres : 4 statuts (Tous/Soleil/Bientôt/Ombre) + 5 types
   - Time slider 6h-22h avec bouton **MAINTENANT** + LIVE pill
   - Badge météo permanent en haut
   - **Bouton GPS "Me localiser"** flottant
   - **Compteur freemium** discret en bas + modal "Soleia Premium"
   - Format heures français partout : "14h30", "Soleil jusqu'à 17h"
5. **Écran Fiche terrasse** :
   - Photo hero + badge statut
   - Card Aujourd'hui : "6h de soleil aujourd'hui" bold + ranges "Soleil de 12h30 à 18h30"
   - Si aucun soleil : "Pas de soleil aujourd'hui · Orientation sud"
   - Slider de temps à une autre heure
   - Prévisions heure par heure (FR)
   - Description IA Claude (contexte nantais : Loire, île de Nantes, Graslin, Bouffay)
   - Bouton "Y aller" (Google Maps)

## Ville MVP
**Nantes** (ville de test) : 20 terrasses réelles avec GPS et orientations en degrés
- Centre: lat 47.2184, lng -1.5536
- La Cigale, Le Lieu Unique, Le Hangar à Bananes, La Brasserie Félix, Le Nid (rooftop),
  Café du Commerce, Bar en Île, Le Trois Mâts, Café Pascaline, L'Atelier, Le Steinway,
  La Maison Bar, Le Bouchon, Café de la Paix, Le Mercure, La Cantine du Voyage,
  Le Perroquet Ivre, Café Madeleine, Le Floride, La Terrasse des Machines.

## Villes supportées (cities API)
Nantes (primaire), Paris, Lyon, Marseille, Bordeaux, Toulouse, Strasbourg,
Lille, Nice, Montpellier, Rennes, Grenoble.

## Stack
- Backend: FastAPI + MongoDB + pysolar + httpx + emergentintegrations
- Frontend: Expo SDK 54, expo-router, react-native-maps, expo-location, @react-native-community/slider
- IA: Claude Sonnet 4 via EMERGENT_LLM_KEY
- Météo: Open-Meteo API

## Modèle Freemium
- Gratuit: 5 recherches/jour (compteur fictif pour l'instant, affiche toujours 5/5)
- Premium 2,99€/mois: illimité, alertes, planificateur, IA perso
- Modal "Bientôt disponible" — Stripe en Phase 3

## Out of MVP (Phase 2/3)
- Notifications push
- Recommandations IA personnalisées
- Planificateur avancé
- Auth Google Emergent
- Stripe
- Autres villes données complètes

## Tests
18/18 tests backend passent avec Nantes (pytest)
