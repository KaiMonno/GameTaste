import type { RecommendationResult } from "@/lib/api";

export default function ResultsList({ results }: { results: RecommendationResult[] }) {
  if (results.length === 0) {
    return <p className="text-gray-500">No results yet — submit the form above.</p>;
  }

  return (
    <ul className="space-y-3">
      {results.map((r) => (
        <li key={r.game.id} className="rounded border border-gray-200 bg-white p-4">
          <div className="flex items-baseline justify-between">
            <h3 className="font-semibold">{r.game.name}</h3>
            <span className="text-sm text-gray-500">{r.match_score}% match</span>
          </div>
          {r.game.summary && <p className="mt-1 text-sm text-gray-600 line-clamp-2">{r.game.summary}</p>}
          {r.why_recommended && <p className="mt-2 text-sm text-green-700">{r.why_recommended}</p>}
          {r.why_not && <p className="text-sm text-amber-700">{r.why_not}</p>}
        </li>
      ))}
    </ul>
  );
}
