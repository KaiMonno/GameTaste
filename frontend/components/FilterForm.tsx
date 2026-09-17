"use client";

import { useEffect, useState } from "react";
import { getFacets, type HardFilters, type SoftPreferences } from "@/lib/api";

interface Props {
  onSubmit: (hardFilters: HardFilters, softPreferences: SoftPreferences) => void;
  loading: boolean;
}

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

function PillToggle({
  options,
  selected,
  onChange,
}: {
  options: string[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((option) => {
        const active = selected.includes(option);
        return (
          <button
            key={option}
            type="button"
            onClick={() => onChange(toggle(selected, option))}
            className={`rounded-full border px-3 py-1 text-sm ${
              active
                ? "border-gray-900 bg-gray-900 text-white"
                : "border-gray-300 bg-white text-gray-700"
            }`}
          >
            {option}
          </button>
        );
      })}
    </div>
  );
}

export default function FilterForm({ onSubmit, loading }: Props) {
  const [platformOptions, setPlatformOptions] = useState<string[]>([]);
  const [genreOptions, setGenreOptions] = useState<string[]>([]);
  const [facetsError, setFacetsError] = useState<string | null>(null);

  const [platforms, setPlatforms] = useState<string[]>([]);
  const [genres, setGenres] = useState<string[]>([]);
  const [requireMultiplayer, setRequireMultiplayer] = useState(false);
  const [minReviewScore, setMinReviewScore] = useState<string>("");
  const [targetLengthHours, setTargetLengthHours] = useState<string>("");
  const [targetStoryGameplayRatio, setTargetStoryGameplayRatio] = useState<string>("");
  const [targetPopularity, setTargetPopularity] = useState<string>("");

  useEffect(() => {
    getFacets()
      .then((facets) => {
        setPlatformOptions(facets.platforms);
        setGenreOptions(facets.genres);
      })
      .catch((err) => setFacetsError(err instanceof Error ? err.message : "Failed to load filter options"));
  }, []);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    const hardFilters: HardFilters = {
      // Mobile platforms and DLC/expansions are always excluded server-side -
      // not a user-facing option, see backend/app/services/scoring.py.
      include_genres: genres,
      exclude_genres: [],
      platforms,
      require_multiplayer: requireMultiplayer,
      min_review_score: minReviewScore ? Number(minReviewScore) : null,
    };

    const softPreferences: SoftPreferences = {
      target_length_hours: targetLengthHours ? Number(targetLengthHours) : null,
      target_story_gameplay_ratio: targetStoryGameplayRatio ? Number(targetStoryGameplayRatio) : null,
      target_popularity: targetPopularity ? Number(targetPopularity) : null,
      // "Similar to a specific game" needs a game-search UI to pick a
      // reference game - not built yet, left for a later pass.
      similar_to_game_id: null,
    };

    onSubmit(hardFilters, softPreferences);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 max-w-md">
      <div>
        <label className="block text-sm font-medium">Target length (hours)</label>
        <input
          type="number"
          value={targetLengthHours}
          onChange={(e) => setTargetLengthHours(e.target.value)}
          className="mt-1 w-full rounded border border-gray-300 px-3 py-2"
          placeholder="e.g. 15"
        />
      </div>

      <div>
        <label className="block text-sm font-medium">Story vs. gameplay focus (0-100)</label>
        <p className="text-xs text-gray-500">0 = pure gameplay, 100 = pure narrative. AI-estimated per game.</p>
        <input
          type="number"
          min={0}
          max={100}
          value={targetStoryGameplayRatio}
          onChange={(e) => setTargetStoryGameplayRatio(e.target.value)}
          className="mt-1 w-full rounded border border-gray-300 px-3 py-2"
          placeholder="e.g. 70 for story-heavy"
        />
      </div>

      <div>
        <label className="block text-sm font-medium">Popularity target (0-100)</label>
        <p className="text-xs text-gray-500">
          0 = most niche/hidden-gem, 100 = most mainstream. Relative to the games matching your other filters.
        </p>
        <input
          type="number"
          min={0}
          max={100}
          value={targetPopularity}
          onChange={(e) => setTargetPopularity(e.target.value)}
          className="mt-1 w-full rounded border border-gray-300 px-3 py-2"
          placeholder="e.g. 15 for a hidden gem, 85 for mainstream"
        />
      </div>

      <div>
        <label className="block text-sm font-medium">Minimum review score (0-100)</label>
        <input
          type="number"
          min={0}
          max={100}
          value={minReviewScore}
          onChange={(e) => setMinReviewScore(e.target.value)}
          className="mt-1 w-full rounded border border-gray-300 px-3 py-2"
          placeholder="e.g. 70"
        />
      </div>

      {facetsError && <p className="text-sm text-red-600">{facetsError}</p>}

      <div>
        <label className="block text-sm font-medium">Platform</label>
        <p className="text-xs text-gray-500">Leave empty to include all platforms.</p>
        <div className="mt-2 max-h-48 overflow-y-auto rounded border border-gray-200 p-2">
          {platformOptions.length > 0 ? (
            <PillToggle options={platformOptions} selected={platforms} onChange={setPlatforms} />
          ) : (
            <p className="text-sm text-gray-400">Loading platforms...</p>
          )}
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium">Genre</label>
        <p className="text-xs text-gray-500">Leave empty to include all genres.</p>
        <div className="mt-2 max-h-48 overflow-y-auto rounded border border-gray-200 p-2">
          {genreOptions.length > 0 ? (
            <PillToggle options={genreOptions} selected={genres} onChange={setGenres} />
          ) : (
            <p className="text-sm text-gray-400">Loading genres...</p>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          id="requireMultiplayer"
          checked={requireMultiplayer}
          onChange={(e) => setRequireMultiplayer(e.target.checked)}
        />
        <label htmlFor="requireMultiplayer" className="text-sm">
          Require multiplayer
        </label>
      </div>

      <button
        type="submit"
        disabled={loading}
        className="rounded bg-gray-900 px-4 py-2 text-white disabled:opacity-50"
      >
        {loading ? "Finding games..." : "Get recommendations"}
      </button>
    </form>
  );
}
