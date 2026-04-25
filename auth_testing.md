# Emergent Google Auth — Testing Playbook

## Testing Guide (adapted for Expo mobile + FastAPI)

### Step 1: Create Test User & Session manually (curl / mongosh)

```bash
# via mongosh
mongosh --eval "
use('suntterrace_db');
var userId = 'test-user-' + Date.now();
var sessionToken = 'test_session_' + Date.now();
db.users.insertOne({
  user_id: userId,
  email: 'test.user.' + Date.now() + '@example.com',
  name: 'Test User',
  picture: 'https://via.placeholder.com/150',
  created_at: new Date()
});
db.user_sessions.insertOne({
  user_id: userId,
  session_token: sessionToken,
  expires_at: new Date(Date.now() + 7*24*60*60*1000),
  created_at: new Date()
});
print('Session token: ' + sessionToken);
print('User ID: ' + userId);
"
```

### Step 2: Backend API tests

```bash
# /auth/me protected — should return user data
curl -H "Authorization: Bearer $TOKEN" https://sunny-terraces.preview.emergentagent.com/api/auth/me

# /favorites/me with auth
curl -H "Authorization: Bearer $TOKEN" https://sunny-terraces.preview.emergentagent.com/api/auth/favorites

# Write favorites
curl -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"favorite_ids":["57c290ff-05bc-402f-afca-d9e939322808"]}' \
  https://sunny-terraces.preview.emergentagent.com/api/auth/favorites
```

### Expected behaviour

- ✅ /api/auth/me returns `{user_id, email, name, picture}` with valid session
- ✅ /api/auth/me returns 401 without session
- ✅ /api/auth/favorites persists favorite_ids per user
- ✅ Favorites survive app reinstall (cross-device)
- ✅ Local AsyncStorage favorites merged into server on first login

### Expo mobile test (manual)

1. Open app → Profile screen → tap "Se connecter"
2. Google OAuth page opens in Chrome Custom Tab (Android) / ASWebAuthenticationSession (iOS)
3. Complete Google sign-in
4. App receives session_id via deep link `soleia://auth?session_id=...`
5. App exchanges session_id for session_token → stores in SecureStore
6. Profile now shows user name + email
7. Add a favorite → verified it's synced to server
8. Reinstall app → log back in → favorites restored

### Test Identity Tracking

No app-managed passwords for Google OAuth. Test identities listed in /app/memory/test_credentials.md.
