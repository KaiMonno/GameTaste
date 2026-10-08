import type { RecommendationResult } from "@/lib/api";

// match_score/why_recommended/why_not only exist for the search that
// produced them - there's no backend endpoint that returns them for an
// arbitrary game id outside that context. Rather than round-tripping them
// through the URL (long, ugly, and they're prose - awkward to query-string
// encode), the last search's full results are stashed here and the detail
// page (app/games/[id]/page.tsx) looks itself up by id on mount.
//
// sessionStorage, not a plain module variable: survives a full page reload
// of the detail page (e.g. the user refreshes, or opens it in a new tab via
// "open link") within the same browser tab's session, which a module-level
// variable would not.
const STORAGE_KEY = "gametaste:lastResults";

export function saveLastResults(results: RecommendationResult[]): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(results));
  } catch {
    // Best-effort cache - if sessionStorage is unavailable (private
    // browsing, quota), the detail page just falls back to the plain
    // GET /games/{id} view with no match-specific info. Not worth
    // surfacing an error for.
  }
}

export function getCachedResult(gameId: number): RecommendationResult | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const results: RecommendationResult[] = JSON.parse(raw);
    return results.find((r) => r.game.id === gameId) ?? null;
  } catch {
    return null;
  }
}
