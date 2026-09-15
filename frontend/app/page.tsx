"use client";

import { useState } from "react";
import FilterForm from "@/components/FilterForm";
import ResultsList from "@/components/ResultsList";
import { getRecommendations, type HardFilters, type RecommendationResult, type SoftPreferences } from "@/lib/api";

export default function Home() {
  const [results, setResults] = useState<RecommendationResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(hardFilters: HardFilters, softPreferences: SoftPreferences) {
    setLoading(true);
    setError(null);
    try {
      const data = await getRecommendations(hardFilters, softPreferences);
      setResults(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="text-2xl font-bold">GameTaste</h1>
      <p className="mt-1 text-gray-600">Tell us what you want, we'll find the game.</p>

      <div className="mt-8">
        <FilterForm onSubmit={handleSubmit} loading={loading} />
      </div>

      {error && <p className="mt-6 text-red-600">{error}</p>}

      <div className="mt-8">
        <ResultsList results={results} />
      </div>
    </main>
  );
}
