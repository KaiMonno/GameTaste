"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth, SignedIn } from "@clerk/nextjs";
import FilterForm from "@/components/FilterForm";
import ResultsList from "@/components/ResultsList";
import SteamImport from "@/components/SteamImport";
import {
  getPreferences,
  getRecommendations,
  savePreferences,
  type HardFilters,
  type RecommendationResult,
  type SoftPreferences,
} from "@/lib/api";

/** Reads the ?steam=success|error result the OpenID callback redirects
 * back to (see app/api/steam-openid/callback/route.ts) and clears it from
 * the URL once shown, so a page refresh doesn't keep re-displaying a
 * stale result. Split out and wrapped in Suspense because useSearchParams
 * requires that in the App Router.
 */
function SteamImportBanner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const steam = searchParams.get("steam");

  useEffect(() => {
    if (steam) router.replace("/", { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [steam]);

  if (!steam) return null;

  if (steam === "success") {
    const total = searchParams.get("total");
    const matched = searchParams.get("matched");
    const unmatched = Number(searchParams.get("unmatched") ?? "0");
    return (
      <p className="mt-4 text-sm text-green-700">
        Steam library imported - found {total} owned games, {matched} excluded from your
        recommendations{unmatched > 0 ? ` (${unmatched} aren't in our catalog)` : ""}.
      </p>
    );
  }

  return (
    <p className="mt-4 text-sm text-red-600">
      {searchParams.get("message") ?? "Something went wrong signing in with Steam"}
    </p>
  );
}

export default function Home() {
  const { isSignedIn, getToken } = useAuth();
  const [results, setResults] = useState<RecommendationResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [initialHardFilters, setInitialHardFilters] = useState<HardFilters | undefined>(undefined);
  const [initialSoftPreferences, setInitialSoftPreferences] = useState<SoftPreferences | undefined>(undefined);
  const [saveDefaultsState, setSaveDefaultsState] = useState<"idle" | "saving" | "saved" | "error">("idle");

  useEffect(() => {
    if (!isSignedIn) return;
    (async () => {
      try {
        const token = await getToken();
        const saved = await getPreferences(token);
        if (saved) {
          setInitialHardFilters(saved.hard_filters);
          setInitialSoftPreferences(saved.soft_preferences);
        }
      } catch {
        // Saved defaults are a convenience, not required - the form's own
        // blank defaults are a fine fallback if this fails.
      }
    })();
  }, [isSignedIn, getToken]);

  async function handleSubmit(hardFilters: HardFilters, softPreferences: SoftPreferences) {
    setLoading(true);
    setError(null);
    try {
      const token = isSignedIn ? await getToken() : null;
      const data = await getRecommendations(hardFilters, softPreferences, token);
      setResults(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  async function handleSaveDefaults(hardFilters: HardFilters, softPreferences: SoftPreferences) {
    setSaveDefaultsState("saving");
    try {
      const token = await getToken();
      await savePreferences(token, hardFilters, softPreferences);
      setSaveDefaultsState("saved");
    } catch {
      setSaveDefaultsState("error");
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="text-2xl font-bold">GameTaste</h1>
      <p className="mt-1 text-gray-600">Tell us what you want, we'll find the game.</p>

      <SignedIn>
        <div className="mt-8">
          <SteamImport />
          <Suspense fallback={null}>
            <SteamImportBanner />
          </Suspense>
        </div>
      </SignedIn>

      <div className="mt-8">
        <FilterForm
          onSubmit={handleSubmit}
          loading={loading}
          initialHardFilters={initialHardFilters}
          initialSoftPreferences={initialSoftPreferences}
          onSaveDefaults={isSignedIn ? handleSaveDefaults : undefined}
          saveDefaultsState={saveDefaultsState}
        />
      </div>

      {error && <p className="mt-6 text-red-600">{error}</p>}

      <div className="mt-8">
        <ResultsList results={results} />
      </div>
    </main>
  );
}
