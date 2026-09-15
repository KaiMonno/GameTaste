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
  difficulty_score: number | null;
  story_gameplay_ratio: number | null;
  content_warnings: string[];
}

export interface RecommendationResult {
  game: GameOut;
  match_score: number;
  why_recommended: string | null;
  why_not: string | null;
}

export interface HardFilters {
  exclude_genres: string[];
  platforms: string[];
  exclude_mobile: boolean;
  exclude_content_warnings: string[];
  require_multiplayer: boolean;
  min_review_score: number | null;
}

export interface SoftPreferences {
  target_length_hours: number | null;
  target_difficulty: number | null;
  target_story_gameplay_ratio: number | null;
  target_popularity: number | null;
  similar_to_game_id: number | null;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function getRecommendations(
  hardFilters: HardFilters,
  softPreferences: SoftPreferences,
  limit = 20
): Promise<RecommendationResult[]> {
  const res = await fetch(`${API_URL}/recommendations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ hard_filters: hardFilters, soft_preferences: softPreferences, limit }),
  });

  if (!res.ok) {
    throw new Error(`Recommendation request failed: ${res.status}`);
  }

  const data = await res.json();
  return data.results;
}
