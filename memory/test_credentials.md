# Soleia — Test credentials

## Auth (Emergent Google OAuth)

For backend tests only, a test user + session can be manually created in MongoDB.
Google OAuth uses no app-managed password: sessions are created via the Emergent service.

### Test identity (created during backend validation)

- Email: test-auth-flow@example.com
- session_token stored in MongoDB `user_sessions` collection, TTL 30 days
- To (re)create: run the snippet in /app/auth_testing.md

### Manual backend endpoints validation

```bash
TOK="stk_test_<hex>"  # from db.user_sessions
BASE="https://sunny-terraces.preview.emergentagent.com"

curl -H "Authorization: Bearer $TOK" $BASE/api/auth/me
curl -H "Authorization: Bearer $TOK" $BASE/api/auth/favorites
curl -X PUT -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d '{"favorite_ids":["aaa","bbb"]}' $BASE/api/auth/favorites
curl -X POST -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d '{"favorite_ids":["ccc"]}' $BASE/api/auth/favorites/merge
curl -X POST -H "Authorization: Bearer $TOK" $BASE/api/auth/logout
```

## Mobile login (end-to-end)

Use a real Google account. The app opens:
`https://auth.emergentagent.com/?redirect=<BACKEND>/api/auth/mobile-callback`
Emergent redirects to our HTML page which deep-links back via `soleia://auth?session_id=<id>`.
The app then POSTs `/api/auth/session` to exchange the session_id for `session_token`.

## Other tested routes

- GET /api/terraces (bbox filtered, 10680 establishments)
- GET /api/shadows (OSM 3D)
- GET /api/weather/:city
- POST /api/terraces/:id/generate-description (Claude)
- GET /api/auth/mobile-callback (HTML bridge page, no auth)

## DB constants

- MONGO_URL = mongodb://localhost:27017
- DB_NAME = suntterrace_db
- Collections: terraces (10680), users, user_sessions
