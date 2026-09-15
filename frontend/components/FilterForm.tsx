"use client";

import { useState } from "react";
import type { HardFilters, SoftPreferences } from "@/lib/api";

interface Props {
  onSubmit: (hardFilters: HardFilters, softPreferences: SoftPreferences) => void;
  loading: boolean;
}

export default function FilterForm({ onSubmit, loading }: Props) {
  const [excludeMobile, setExcludeMobile] = useState(true);
  const [requireMultiplayer, setRequireMultiplayer] = useState(false);
  const [minReviewScore, setMinReviewScore] = useState<string>("");
  const [targetLengthHours, setTargetLengthHours] = useState<string>("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    const hardFilters: HardFilters = {
      exclude_genres: [],
      platforms: [],
      exclude_mobile: excludeMobile,
      exclude_content_warnings: [],
      require_multiplayer: requireMultiplayer,
      min_review_score: minReviewScore ? Number(minReviewScore) : null,
    };

    const softPreferences: SoftPreferences = {
      target_length_hours: targetLengthHours ? Number(targetLengthHours) : null,
      target_story_gameplay_ratio: null,
      target_popularity: null,
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

      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          id="excludeMobile"
          checked={excludeMobile}
          onChange={(e) => setExcludeMobile(e.target.checked)}
        />
        <label htmlFor="excludeMobile" className="text-sm">
          Exclude mobile platforms
        </label>
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
