export interface GameOut {
  id: number;
  name: string;
  summary: string | null;
  genres: string[];
  platforms: string[];
  game_modes: string[];
  igdb_rating: number | null;
  igdb_rating_count: number | null;
  hltb_main: number | null;
  hltb_main_extra: number | null;
  hltb_completionist: number | null;
  story_gameplay_ratio: number | null;
  custom_categories: string[];
  cover_url: string | null;
}

export interface RecommendationResult {
  game: GameOut;
  match_score: number;
  why_recommended: string | null;
  why_not: string | null;
}

export interface HardFilters {
  include_genres: string[];
  exclude_genres: string[];
  platforms: string[];
  require_multiplayer: boolean;
}

export interface SoftPreferences {
  target_length_hours: number | null;
  target_story_gameplay_ratio: number | null;
  // No target_popularity - IGDB popularity is no longer a user preference.
  // A small, always-on discovery bias toward less-obvious games applies
  // automatically server-side instead (see backend/app/services/scoring.py).
  similar_to_game_id: number | null;
}

export interface Facets {
  genres: string[];
  platforms: string[];
}

export interface UserPreferences {
  hard_filters: HardFilters;
  soft_preferences: SoftPreferences;
}

export interface WishlistItem {
  game: GameOut;
  added_at: string;
}

export interface SteamImportResult {
  total_owned: number;
  matched: number;
  unmatched: number;
}

export interface SteamStatus {
  linked: boolean;
  game_count: number;
  last_synced_at: string | null;
}

export interface OwnedPlatforms {
  owned_platforms: string[];
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Phase 5: preferences/wishlist are the only endpoints that require a signed-
// in user - callers get the token from Clerk's useAuth().getToken() (client
// components) and pass it through here, since this module isn't itself a
// component and can't call hooks. A null/missing token on a protected call
// surfaces as the backend's 401, not a thrown error here - the caller
// decides how to handle "not signed in".
function authHeaders(token: string | null): HeadersInit {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// Genre/platform values actually present in the synced catalog - drives the
// filter form's options so they never drift from real data (mobile platforms
// are omitted server-side since they're always excluded from results).
// `genres` includes both IGDB genres and our own custom categories (Horror,
// Roguelike, ...) as one combined list - no distinction needed here.
export async function getFacets(): Promise<Facets> {
  const res = await fetch(`${API_URL}/games/facets`);

  if (!res.ok) {
    throw new Error(`Failed to load filter options: ${res.status}`);
  }

  return res.json();
}

// Fallback for the game detail page when there's no cached search result
// for this id (e.g. a reload after sessionStorage was cleared, or a direct
// link) - plain game data only, no match_score/why_recommended/why_not,
// since those only exist in the context of a specific search.
export async function getGame(id: number): Promise<GameOut | null> {
  const res = await fetch(`${API_URL}/games/${id}`);

  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Failed to load game: ${res.status}`);
  }

  return res.json();
}

export async function getRecommendations(
  hardFilters: HardFilters,
  softPreferences: SoftPreferences,
  // Optional: signed-in and sent, the backend excludes this user's Steam-
  // imported library from results (Phase 6) - omitted or null, search
  // behaves exactly as it did signed-out.
  token: string | null = null
): Promise<RecommendationResult[]> {
  const res = await fetch(`${API_URL}/recommendations`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ hard_filters: hardFilters, soft_preferences: softPreferences }),
  });

  if (!res.ok) {
    throw new Error(`Recommendation request failed: ${res.status}`);
  }

  const data = await res.json();
  return data.results;
}

export async function getPreferences(token: string | null): Promise<UserPreferences | null> {
  const res = await fetch(`${API_URL}/profile/preferences`, { headers: authHeaders(token) });

  if (res.status === 401) return null;
  if (!res.ok) throw new Error(`Failed to load saved preferences: ${res.status}`);

  return res.json();
}

export async function savePreferences(
  token: string | null,
  hardFilters: HardFilters,
  softPreferences: SoftPreferences
): Promise<UserPreferences> {
  const res = await fetch(`${API_URL}/profile/preferences`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ hard_filters: hardFilters, soft_preferences: softPreferences }),
  });

  if (!res.ok) throw new Error(`Failed to save preferences: ${res.status}`);
  return res.json();
}

export async function getWishlist(token: string | null): Promise<WishlistItem[]> {
  const res = await fetch(`${API_URL}/wishlist`, { headers: authHeaders(token) });

  if (res.status === 401) return [];
  if (!res.ok) throw new Error(`Failed to load wishlist: ${res.status}`);

  return res.json();
}

export async function addToWishlist(token: string | null, gameId: number): Promise<void> {
  const res = await fetch(`${API_URL}/wishlist/${gameId}`, { method: "POST", headers: authHeaders(token) });
  if (!res.ok) throw new Error(`Failed to save game: ${res.status}`);
}

export async function removeFromWishlist(token: string | null, gameId: number): Promise<void> {
  const res = await fetch(`${API_URL}/wishlist/${gameId}`, { method: "DELETE", headers: authHeaders(token) });
  if (!res.ok) throw new Error(`Failed to remove game: ${res.status}`);
}

// Excludes a game from this user's future recommendations - the manual
// counterpart to a Steam import (see backend/app/models.py
// UserLibraryItem). Both end up excluding the same way, so there's no
// separate "played" concept on the backend to keep in sync with.
export async function markAsPlayed(token: string | null, gameId: number): Promise<void> {
  const res = await fetch(`${API_URL}/profile/played/${gameId}`, { method: "POST", headers: authHeaders(token) });
  if (!res.ok) throw new Error(`Failed to mark as played: ${res.status}`);
}

export async function unmarkAsPlayed(token: string | null, gameId: number): Promise<void> {
  const res = await fetch(`${API_URL}/profile/played/${gameId}`, { method: "DELETE", headers: authHeaders(token) });
  if (!res.ok) throw new Error(`Failed to undo: ${res.status}`);
}

export async function importSteamLibrary(token: string | null, steamIdentifier: string): Promise<SteamImportResult> {
  const res = await fetch(`${API_URL}/profile/steam-import`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ steam_identifier: steamIdentifier }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Steam import failed: ${res.status}`);
  }
  return res.json();
}

export async function getSteamStatus(token: string | null): Promise<SteamStatus> {
  const res = await fetch(`${API_URL}/profile/steam-status`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(`Failed to load Steam status: ${res.status}`);
  return res.json();
}

export async function getOwnedPlatforms(token: string | null): Promise<OwnedPlatforms> {
  const res = await fetch(`${API_URL}/profile/owned-platforms`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(`Failed to load owned platforms: ${res.status}`);
  return res.json();
}

export async function saveOwnedPlatforms(token: string | null, ownedPlatforms: string[]): Promise<OwnedPlatforms> {
  const res = await fetch(`${API_URL}/profile/owned-platforms`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ owned_platforms: ownedPlatforms }),
  });
  if (!res.ok) throw new Error(`Failed to save owned platforms: ${res.status}`);
  return res.json();
}
