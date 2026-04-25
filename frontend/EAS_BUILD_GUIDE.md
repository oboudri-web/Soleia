# Soleia — EAS Build Guide (Dev Build + Prod)

Guide rapide pour builder Soleia en development build (dev client) + production.

## 📋 Prérequis

1. Compte Expo (gratuit) : https://expo.dev/signup
2. EAS CLI : `npm install -g eas-cli`
3. Pour iOS TestFlight / App Store :
   - Compte Apple Developer ($99/an)
   - Team ID + App Store Connect app créé
4. Pour Android Play Store :
   - Google Play Console account ($25 one-time)
   - Service account JSON

## 🚀 Premier build (development)

```bash
cd /app/frontend

# Login
eas login

# Initialize EAS project (première fois seulement)
eas init
# → Créé un projectId et l'ajoute dans app.json > extra.eas.projectId

# Build dev client pour iOS + Android en parallèle
eas build --profile development --platform all

# Durée : ~10-20 min par plateforme (build en cloud Expo)
# Résultat : lien de téléchargement .ipa (iOS) + .apk (Android)
```

## 📱 Installation dev build sur téléphone

**iOS :** 
- Utilise TestFlight ou scan le QR code EAS après build
- Device doit être enregistré : `eas device:create`

**Android :**
- Télécharge le .apk et ouvre-le (autoriser "sources inconnues")

Une fois installée, lance l'app custom → scan le QR code Metro local → l'app charge directement ton code, comme Expo Go mais avec TOUS les native modules (react-native-maps 100% supporté, expo-notifications complet, etc.).

## 🧪 Builds suivants

```bash
# Dev simulator iOS (rapide, sur Mac uniquement)
eas build --profile development-simulator --platform ios

# Preview (APK/IPA distribuables internes)
eas build --profile preview --platform all

# Production (pour App Store / Play Store)
eas build --profile production --platform all
```

## 📤 Soumission stores

```bash
# iOS App Store
eas submit --platform ios --profile production

# Google Play Store  
eas submit --platform android --profile production
```

## 🔧 Variables à remplacer dans eas.json

Avant le premier `eas submit`, édite `eas.json` → `submit.production` :
- `appleId` : ton Apple ID
- `ascAppId` : App Store Connect App ID (10 digits)
- `appleTeamId` : Team ID (10 chars, dans Apple Dev portal)
- `serviceAccountKeyPath` : chemin local du JSON Google Play service account

## 🎯 Backend URL

Le build utilise `EXPO_PUBLIC_BACKEND_URL` défini dans `eas.json > build.base.env`. 
Actuellement : `https://sunny-terraces.preview.emergentagent.com`

Avant release prod : changer pour l'URL backend de production.

## ⚡ Pourquoi le dev build ?

Expo Go SDK 53+ a des limitations fondamentales :
- 200+ markers sur react-native-maps → crash natif (rencontré)
- expo-notifications partiellement cassé (push tokens ne fonctionnent pas)
- Pas de custom native modules (impossible Google Maps 3D SDK)

**Dev build = Expo Go mais sans limites.** C'est l'étape obligatoire avant App Store/Play Store de toute façon.

## 📊 Estimé temps pour release prod

1. EAS setup : 30 min
2. First dev build + test devices : 1 h
3. Fix bugs éventuels rencontrés uniquement en prod build : 1-3 j
4. App Store review : 24-72 h
5. Play Store review : ~3 h (auto) puis 1-2 j (manuel si nouveau compte)

**Total réaliste : 4-6 jours avant être live sur les 2 stores.**
