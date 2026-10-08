"use client";

import Link from "next/link";
import { BookOpen } from "lucide-react";
import type { RecommendationResult } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

// Decorative-only "book cover" colors cycled per result, independent of
// the semantic theme tokens - same palette the BookshelfBanner illustration
// and the detail page's fallback cover use, so a game with no real box art
// still looks intentional rather than like a broken image.
const SPINE_COLORS = ["--spine-1", "--spine-2", "--spine-3", "--spine-4", "--spine-5"] as const;

function matchBadgeVariant(score: number): "default" | "secondary" | "outline" {
  if (score >= 85) return "default";
  if (score >= 60) return "secondary";
  return "outline";
}

function FallbackCover({ name, spineVar }: { name: string; spineVar: string }) {
  return (
    <div
      className="flex h-full w-full flex-col items-center justify-center gap-2 p-3 text-center"
      style={{ backgroundColor: spineVar }}
    >
      <BookOpen className="size-6 text-white/80" aria-hidden="true" />
      <span className="line-clamp-4 text-xs font-medium text-white/90">{name}</span>
    </div>
  );
}

export default function ResultsList({ results }: { results: RecommendationResult[] }) {
  if (results.length === 0) {
    return <p className="text-sm text-muted-foreground">No results yet — submit the form above.</p>;
  }

  return (
    <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-5">
      {results.map((r, index) => {
        const spineVar = `var(${SPINE_COLORS[index % SPINE_COLORS.length]})`;
        return (
          <li key={r.game.id}>
            <Link
              href={`/games/${r.game.id}`}
              className="group block overflow-hidden rounded-lg border bg-card transition-shadow hover:shadow-md"
            >
              <div className="relative aspect-[3/4] overflow-hidden bg-muted">
                {r.game.cover_url ? (
                  // eslint-disable-next-line @next/next/no-img-element -- external IGDB CDN image, no next/image remote-pattern config needed for a plain <img>
                  <img
                    src={r.game.cover_url}
                    alt={r.game.name}
                    loading="lazy"
                    className="h-full w-full object-cover transition-transform group-hover:scale-105"
                  />
                ) : (
                  <FallbackCover name={r.game.name} spineVar={spineVar} />
                )}
                <Badge variant={matchBadgeVariant(r.match_score)} className="absolute right-1.5 top-1.5 shadow">
                  {r.match_score}%
                </Badge>
              </div>
              <p className="line-clamp-2 p-2 text-sm font-medium">{r.game.name}</p>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
