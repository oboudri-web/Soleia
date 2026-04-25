/**
 * SunTerrace - API Client
 */
const BASE_URL = process.env.EXPO_PUBLIC_BACKEND_URL;

export type SunStatus = 'sunny' | 'soon' | 'shade';

export type Terrace = {
  id: string;
  name: string;
  lat: number;
  lng: number;
  orientation_degrees: number;
  orientation_label: string;
  type: string;
  city: string;
  arrondissement?: string;
  address: string;
  google_rating: number;
  google_ratings_count?: number;
  google_place_id?: string | null;
  google_maps_uri?: string | null;
  has_terrace_confirmed?: boolean;
  terrace_source?: string;
  terrace_confidence?: string | null;
  terrace_covered?: boolean | null;
  terrace_capacity?: 'small' | 'medium' | 'large' | null;
  terrace_ai_notes?: string | null;
  photo_url: string;
  photos?: string[];
  has_cover: boolean;
  capacity_estimate: number;
  ai_description?: string;
  distance_km?: number | null;
  sun_status: SunStatus;
  is_sunny: boolean;
  sun_azimuth: number;
  sun_altitude: number;
  next_sunny_time?: string | null;
  sunny_until?: string | null;
  /** True if the backend enriched `is_sunny` with 3D shadow analysis (OSM ray-cast). */
  shadow_analyzed?: boolean;
  /** True if the shadow analysis disagreed with the orientation heuristic (overrode). */
  shadow_override?: boolean;
  /** Sunny minutes in the shadow-analysed day (pre-computed, between 6h-22h). */
  shadow_sunny_minutes?: number;
  /** Buildings considered in the ray-cast analysis. */
  shadow_buildings_count?: number;
  /** ISO date when the analysis was computed. */
  shadow_analysis_date?: string;

  /** Google Places Details enrichment. */
  opening_hours?: {
    weekday_descriptions: string[];
    periods?: Array<{
      open?: { day?: number; hour?: number; minute?: number };
      close?: { day?: number; hour?: number; minute?: number };
    }>;
  } | null;
  phone_number?: string | null;
  website_uri?: string | null;
  /** 0 = free, 1 = inexpensive, 2 = moderate, 3 = expensive, 4 = very expensive. */
  price_level?: number | null;
  reservable?: boolean | null;
  details_enriched_at?: string | null;
};

export type TerraceDetail = Terrace & {
  sun_schedule_today: {
    sunny_hours: { start: string; end: string; duration_minutes: number }[];
    total_minutes: number;
    first_sunny: string | null;
    last_sunny: string | null;
  };
  hourly_forecast: {
    hour: string;
    is_sunny: boolean;
    sun_azimuth: number;
    sun_altitude: number;
  }[];
};

export type Weather = {
  city: string;
  temperature: number;
  apparent_temperature: number;
  cloud_cover: number;
  uv_index: number;
  wind_speed: number;
  is_day: boolean;
  weather_code: number;
  weather_label: string;
  updated_at: string;
};

export type City = {
  name: string;
  lat: number;
  lng: number;
};

export type NextSunny = {
  found: boolean;
  first_sunny_time?: string;
  first_sunny_iso?: string;
  is_tomorrow?: boolean;
  terrace_id?: string;
  terrace_name?: string;
  terrace_type?: string;
  terrace_photo?: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${BASE_URL}/api${path}`;
  const response = await fetch(url, init);
  if (!response.ok) {
    let detail = '';
    try {
      detail = await response.text();
    } catch {}
    throw new Error(`API error ${response.status}: ${url} ${detail}`);
  }
  return response.json();
}

export const api = {
  async listCities(): Promise<City[]> {
    return request<City[]>('/cities');
  },

  async listTerraces(params: {
    city?: string;
    lat?: number;
    lng?: number;
    radius_km?: number;
    type?: string;
    sun_status?: SunStatus;
    min_rating?: number;
    at_time?: string;
    lat_min?: number;
    lat_max?: number;
    lng_min?: number;
    lng_max?: number;
    limit?: number;
  }): Promise<{ terraces: Terrace[]; count: number; at_time: string }> {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.append(k, String(v));
    });
    return request(`/terraces?${qs.toString()}`);
  },

  async getTerrace(id: string, at_time?: string): Promise<TerraceDetail> {
    const qs = at_time ? `?at_time=${encodeURIComponent(at_time)}` : '';
    return request<TerraceDetail>(`/terraces/${id}${qs}`);
  },

  async getWeather(city: string): Promise<Weather> {
    return request<Weather>(`/weather/${encodeURIComponent(city)}`);
  },

  async getShadowOverlay(params: {
    lat_min: number;
    lat_max: number;
    lng_min: number;
    lng_max: number;
    at_time?: string;
  }): Promise<{
    polygons: Array<Array<[number, number]>>;
    sun: { az: number | null; el: number | null };
    building_count: number;
    cached?: boolean;
  }> {
    const qs = new URLSearchParams({
      lat_min: String(params.lat_min),
      lat_max: String(params.lat_max),
      lng_min: String(params.lng_min),
      lng_max: String(params.lng_max),
    });
    if (params.at_time) qs.append('at_time', params.at_time);
    return request(`/shadows?${qs.toString()}`);
  },

  async generateDescription(id: string): Promise<{ ai_description: string }> {
    const url = `${BASE_URL}/api/terraces/${id}/generate-description`;
    const r = await fetch(url, { method: 'POST' });
    if (!r.ok) throw new Error('Failed to generate description');
    return r.json();
  },

  async getNextSunny(city?: string): Promise<NextSunny> {
    const qs = city ? `?city=${encodeURIComponent(city)}` : '';
    return request<NextSunny>(`/next-sunny${qs}`);
  },

  async searchTerraces(q: string, city?: string, at_time?: string): Promise<{ results: Terrace[]; count: number; q: string }> {
    const qs = new URLSearchParams({ q });
    if (city) qs.append('city', city);
    if (at_time) qs.append('at_time', at_time);
    return request(`/terraces/search?${qs.toString()}`);
  },

  async getFavoritesStatus(ids: string[], at_time?: string): Promise<{ terraces: Terrace[]; count: number }> {
    if (!ids.length) return { terraces: [], count: 0 };
    const qs = at_time ? `?at_time=${encodeURIComponent(at_time)}` : '';
    return request(`/terraces/favorites${qs}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    });
  },

  async registerPushToken(token: string, city?: string, preferences?: Record<string, any>): Promise<{ ok: boolean; id: string }> {
    return request('/notifications/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ push_token: token, city, preferences }),
    });
  },

  async reportTerrace(id: string, type: 'confirmed' | 'wrong_orientation' | 'no_terrace', userId?: string) {
    return request(`/terraces/${id}/report`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type, user_id: userId }),
    });
  },

  async uploadTerracePhoto(id: string, imageBase64: string, caption?: string) {
    return request(`/terraces/${id}/photo`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_base64: imageBase64, caption }),
    });
  },

  async submitTerrace(payload: {
    name: string;
    type: string;
    orientation_label?: string;
    orientation_degrees?: number;
    lat: number;
    lng: number;
    city: string;
    photo_base64?: string;
  }) {
    return request(`/terraces/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  },

  async proContact(payload: {
    establishment_name: string;
    email: string;
    city: string;
    message?: string;
  }) {
    return request(`/pro/contact`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  },
};

// ===========================
// Auth (Emergent Google OAuth)
// ===========================
export type AuthUser = {
  user_id: string;
  email: string;
  name: string;
  picture?: string | null;
  favorite_ids?: string[];
};

async function authRequest<T>(path: string, token?: string, init?: RequestInit): Promise<T> {
  const url = `${BASE_URL}/api/auth${path}`;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((init?.headers as Record<string, string>) || {}),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const response = await fetch(url, { ...init, headers });
  if (!response.ok) {
    let detail = '';
    try { detail = await response.text(); } catch {}
    throw new Error(`Auth API error ${response.status}: ${url} ${detail}`);
  }
  return response.json();
}

export const authApi = {
  /** URL to launch Google Sign-in via Emergent Auth service.
   * The redirect param MUST point to our backend mobile-callback HTML page
   * which then deep-links back to the app with scheme soleia://auth?session_id=<id>.
   */
  buildLoginUrl(): string {
    const callback = `${BASE_URL}/api/auth/mobile-callback`;
    return `https://auth.emergentagent.com/?redirect=${encodeURIComponent(callback)}`;
  },

  async exchangeSession(sessionId: string): Promise<{
    session_token: string;
    user: AuthUser;
    favorite_ids: string[];
  }> {
    return authRequest('/session', undefined, {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
    });
  },

  async me(token: string): Promise<AuthUser> {
    return authRequest('/me', token, { method: 'GET' });
  },

  async logout(token: string): Promise<{ ok: boolean }> {
    return authRequest('/logout', token, { method: 'POST' });
  },

  async getFavorites(token: string): Promise<{ favorite_ids: string[] }> {
    return authRequest('/favorites', token, { method: 'GET' });
  },

  async putFavorites(token: string, favoriteIds: string[]): Promise<{
    ok: boolean;
    favorite_ids: string[];
  }> {
    return authRequest('/favorites', token, {
      method: 'PUT',
      body: JSON.stringify({ favorite_ids: favoriteIds }),
    });
  },

  async mergeFavorites(token: string, localIds: string[]): Promise<{
    ok: boolean;
    favorite_ids: string[];
    added: number;
  }> {
    return authRequest('/favorites/merge', token, {
      method: 'POST',
      body: JSON.stringify({ favorite_ids: localIds }),
    });
  },
};
