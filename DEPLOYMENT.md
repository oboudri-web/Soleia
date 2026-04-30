# Déploiement production Soleia — Render + MongoDB Atlas

Ce guide te permet de basculer le backend FastAPI de l'environnement
preview Emergent vers une infrastructure de production stable, prête
pour le lancement sur l'App Store.

## Architecture cible

```
[App iOS / Android (TestFlight + App Store)]
              │
              │  HTTPS  (api.soleia.app)
              ▼
   ┌─────────────────────────────┐
   │  Render Web Service         │
   │  Frankfurt — Starter $7/mo  │
   │  uvicorn server:app         │
   │  /api/health  /api/terraces │
   └────────────┬────────────────┘
                │  mongodb+srv://
                ▼
   ┌─────────────────────────────┐
   │  MongoDB Atlas              │
   │  Cluster M0 (free) → M10    │
   │  base : soleia              │
   │  ~32k terrasses + analyses  │
   └─────────────────────────────┘
```

## Étape 1 — MongoDB Atlas (≈30 min)

1. Va sur https://cloud.mongodb.com → crée un projet "Soleia"
2. **Build a Cluster** → **M0 Sandbox** (gratuit, 512 Mo) en région
   `eu-west-1 (Ireland)` ou `eu-central-1 (Frankfurt)` — le plus proche
   de tes utilisateurs France
3. **Database Access** → ajoute un user `soleia` avec password fort
   (note-le, on en aura besoin)
4. **Network Access** → ajoute `0.0.0.0/0` (Render utilise des IP
   dynamiques). Tu pourras restreindre plus tard quand Render exposera
   ses ranges fixes.
5. **Connect** → **Drivers** → copie l'URI :
   ```
   mongodb+srv://soleia:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
   ```

## Étape 2 — Migrer la donnée Emergent → Atlas

Sur ta machine **locale** (pas dans le container Emergent — il n'a pas
les outils mongo CLI) :

```bash
# Pré-requis
brew install mongodb-database-tools         # macOS
# ou apt install mongodb-database-tools    # Linux

# Cloner le repo
git clone https://github.com/oboudri-web/Soleia.git
cd Soleia

# Récupérer la base depuis Emergent
# (voir avec le support Emergent comment exposer un mongodump à
#  l'extérieur — le container preview a un Mongo local non exposé)
# Option simple : depuis Emergent, lance dans le container :
#   mongodump --db=suntterrace_db --out=/tmp/dump
# Puis tu télécharges /tmp/dump via Emergent UI ou scp.

# Migration vers Atlas
export TARGET_URI='mongodb+srv://soleia:PASSWORD@cluster0.xxxxx.mongodb.net'
export SOURCE_URI='mongodb://localhost:27017'   # si tu as restauré le dump localement
./backend/scripts/migrate_to_atlas.sh
```

Le script :
- dump `suntterrace_db` depuis le source
- restore en `soleia` côté Atlas (renommage `nsFrom`/`nsTo`)
- affiche un récap des collections et leurs counts

## Étape 3 — Render Web Service

1. Va sur https://render.com → connecte ton compte GitHub
2. **New** → **Blueprint** → sélectionne `oboudri-web/Soleia`
3. Render détecte automatiquement `render.yaml` et propose la création
   du service `soleia-api`
4. Avant de lancer le build, va dans **Environment** et renseigne :
   - `MONGO_URL` = `mongodb+srv://soleia:PASSWORD@cluster0.xxxxx.mongodb.net`
   - `EMERGENT_LLM_KEY` = ta clé Emergent
   - `GOOGLE_PLACES_KEY` = ta clé Google
   - `FOURSQUARE_KEY` = ta clé FSQ
5. **Apply** → Render build + déploie en ~3 min
6. Vérifie que `https://soleia-api.onrender.com/api/health` répond
   `{"status":"ok","db":{"connected":true,...}}`

## Étape 4 — Domaine custom api.soleia.app

1. Sur Render → service `soleia-api` → **Settings** → **Custom Domain**
2. Add → `api.soleia.app`
3. Render te donne une cible CNAME (ex. `soleia-api.onrender.com`)
4. Sur ton registrar DNS (Cloudflare, OVH, etc.) :
   ```
   CNAME  api  →  soleia-api.onrender.com
   TTL    300s (5 min)
   ```
5. Render provisionne automatiquement un certificat Let's Encrypt
   (~5 min). Après quoi `https://api.soleia.app/api/health` répond.

## Étape 5 — EAS production build

Le profil `production` dans `frontend/eas.json` est déjà configuré
pour pointer vers `https://api.soleia.app` :

```bash
cd frontend
eas build --profile production --platform ios
eas submit --profile production --platform ios
```

## Étape 6 — Monitoring & alerting (optionnel mais recommandé)

- **Render** affiche déjà CPU/mémoire/logs en live → **Settings** →
  **Notifications** → activer email sur deploy/health-check failures
- **MongoDB Atlas** → **Alerts** → activer alerts sur connexions
  saturées et stockage > 80%
- **UptimeRobot** (gratuit) → ping `https://api.soleia.app/api/health`
  toutes les 5 min → alerte SMS/email si down

## Coûts mensuels estimés

| Composant         | MVP launch | À l'échelle (10k+ users) |
|-------------------|------------|--------------------------|
| Render Web        | $7         | $25 (Standard)           |
| MongoDB Atlas     | $0 (M0)    | $57 (M10)                |
| Domaine .app      | ~$15/an    | ~$15/an                  |
| **Total**         | **~$8/mo** | **~$83/mo**              |

## Rollback

Si jamais Render plante un déploiement :
- Render UI → **Deploys** → cliquer sur un build précédent → **Rollback**

## Annexe — health-check

L'endpoint `/api/health` :
- pingue MongoDB (fail fast si Atlas KO)
- retourne `{status: "ok"|"degraded", db: {...}, elapsed_ms: …}`
- est utilisé par Render pour redémarrer auto en cas de crash
