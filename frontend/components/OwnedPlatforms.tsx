"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { getFacets, getOwnedPlatforms, saveOwnedPlatforms } from "@/lib/api";
import PlatformPicker, { PRIMARY_PLATFORMS } from "@/components/PlatformPicker";

/** Phase 7: platforms/consoles the user actually owns - a persistent,
 * always-on exclusion applied to every search (see backend
 * services/scoring.py exclude_unplayable_platforms), not a per-search
 * filter like the one on the home page's FilterForm. Lives on its own
 * here rather than folded into "Save as my default filters", since that
 * endpoint replaces the whole saved-filters blob on every save - an
 * unrelated field tacked onto it would get silently clobbered whenever
 * either page saved without the other's current value in hand.
 */
export default function OwnedPlatforms() {
  const { getToken } = useAuth();
  const [platformOptions, setPlatformOptions] = useState<string[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [showAll, setShowAll] = useState(false);
  const [state, setState] = useState<"loading" | "idle" | "saving" | "saved" | "error">("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [facets, token] = await Promise.all([getFacets(), getToken()]);
      const owned = await getOwnedPlatforms(token);
      setPlatformOptions(facets.platforms);
      setSelected(owned.owned_platforms);
      if (owned.owned_platforms.some((p) => !PRIMARY_PLATFORMS.includes(p))) {
        setShowAll(true);
      }
      setState("idle");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
      setState("error");
    }
  }, [getToken]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSave() {
    setState("saving");
    setError(null);
    try {
      const token = await getToken();
      const result = await saveOwnedPlatforms(token, selected);
      setSelected(result.owned_platforms);
      setState("saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
      setState("error");
    }
  }

  // Same fix as FilterForm's "Save as my default filters" button -
  // without this, "Saved" would keep reading as current after a further
  // edit that hasn't actually been saved yet.
  function handleChange(next: string[]) {
    setSelected(next);
    if (state === "saved") setState("idle");
  }

  return (
    <div className="rounded border border-gray-200 bg-white p-4">
      <h2 className="font-semibold">Platforms you own</h2>
      <p className="mt-1 text-sm text-gray-600">
        Games unavailable on any of these are excluded from your recommendations automatically.
        Leave empty to not filter by platform.
      </p>

      <div className="mt-3">
        {state === "loading" ? (
          <p className="text-sm text-gray-400">Loading...</p>
        ) : (
          <PlatformPicker
            options={platformOptions}
            selected={selected}
            onChange={handleChange}
            showAll={showAll}
            onToggleShowAll={() => setShowAll((prev) => !prev)}
          />
        )}
      </div>

      <button
        type="button"
        onClick={handleSave}
        disabled={state === "loading" || state === "saving"}
        className="mt-3 rounded bg-gray-900 px-4 py-2 text-sm text-white disabled:opacity-50"
      >
        {state === "saving" ? "Saving..." : state === "saved" ? "Saved" : "Save"}
      </button>
      {state === "error" && error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </div>
  );
}
