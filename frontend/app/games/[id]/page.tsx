"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { SignedIn, SignedOut } from "@clerk/nextjs";
import { ArrowLeft, BookOpen } from "lucide-react";
import { getGame, type GameOut, type RecommendationResult } from "@/lib/api";
import { getCachedResult } from "@/lib/resultsCache";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { SaveButton, PlayedButton } from "@/components/GameActions";

// Same decorative cover-color cycle as ResultsList/BookshelfBanner - keyed
// by game id here (rather than position in a list, which this page
// doesn't have) so a given game's fallback color is at least stable
// across visits, not that it needs to match anything specific.
const SPINE_COLORS = ["--spine-1", "--spine-2", "--spine-3", "--spine-4", "--spine-5"] as const;

function matchBadgeVariant(score: number): "default" | "secondary" | "outline" {
  if (score >= 85) return "default";
  if (score >= 60) return "secondary";
  return "outline";
}

type PageState = "loading" | "found-with-match" | "found-plain" | "not-found";

export default function GameDetailPage({ params }: { params: { id: string } }) {
  const gameId = Number(params.id);
  const [result, setResult] = useState<RecommendationResult | null>(null);
  const [fallbackGame, setFallbackGame] = useState<GameOut | null>(null);
  const [state, setState] = useState<PageState>("loading");

  useEffect(() => {
    // match_score/why_recommended/why_not only exist for the search that
    // produced them (see lib/resultsCache.ts) - check there first, and
    // only hit the network for the plain game record if this page was
    // reached some other way (direct link, reload after the cache cleared).
    const cached = getCachedResult(gameId);
    if (cached) {
      setResult(cached);
      setState("found-with-match");
      return;
    }

    (async () => {
      try {
        const game = await getGame(gameId);
        if (game) {
          setFallbackGame(game);
          setState("found-plain");
        } else {
          setState("not-found");
        }
      } catch {
        setState("not-found");
      }
    })();
  }, [gameId]);

  const BackLink = () => (
    <Link href="/" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="size-4" aria-hidden="true" />
      Back to search
    </Link>
  );

  if (state === "loading") {
    return (
      <main className="mx-auto max-w-2xl px-4 py-12">
        <BackLink />
        <p className="mt-6 text-sm text-muted-foreground">Loading...</p>
      </main>
    );
  }

  if (state === "not-found") {
    return (
      <main className="mx-auto max-w-2xl px-4 py-12">
        <BackLink />
        <p className="mt-6 text-sm text-muted-foreground">Couldn&apos;t find that game.</p>
      </main>
    );
  }

  const game = (result ? result.game : fallbackGame)!;
  const spineVar = `var(${SPINE_COLORS[gameId % SPINE_COLORS.length]})`;
  const tags = [...game.genres, ...game.custom_categories];

  return (
    <main className="mx-auto max-w-2xl px-4 py-12">
      <BackLink />

      <div className="mt-6 flex gap-5">
        <div className="relative aspect-[3/4] w-36 shrink-0 overflow-hidden rounded-lg border bg-muted sm:w-48">
          {game.cover_url ? (
            // eslint-disable-next-line @next/next/no-img-element -- external IGDB CDN image, no next/image remote-pattern config needed for a plain <img>
            <img src={game.cover_url} alt={game.name} className="h-full w-full object-cover" />
          ) : (
            <div
              className="flex h-full w-full flex-col items-center justify-center gap-2 p-3 text-center"
              style={{ backgroundColor: spineVar }}
            >
              <BookOpen className="size-8 text-white/80" aria-hidden="true" />
              <span className="text-sm font-medium text-white/90">{game.name}</span>
            </div>
          )}
        </div>

        <div className="flex-1 space-y-2">
          <h1 className="font-heading text-xl font-semibold tracking-tight">{game.name}</h1>
          {result && <Badge variant={matchBadgeVariant(result.match_score)}>{result.match_score}% match</Badge>}
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {tags.map((tag) => (
                <Badge key={tag} variant="outline">
                  {tag}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </div>

      {!result && (
        <Alert className="mt-6">
          <AlertDescription>
            No match info for this game outside of a search - run a new search to see why it was (or wasn&apos;t)
            recommended.
          </AlertDescription>
        </Alert>
      )}

      <div className="mt-6 space-y-4">
        {game.summary && <p className="text-sm text-muted-foreground">{game.summary}</p>}

        {result?.why_recommended && (
          <div>
            <h2 className="font-heading text-sm font-semibold">Why you&apos;ll like it</h2>
            <p className="mt-1 text-sm text-green-700 dark:text-green-400">{result.why_recommended}</p>
          </div>
        )}
        {result?.why_not && (
          <div>
            <h2 className="font-heading text-sm font-semibold">Why you might not</h2>
            <p className="mt-1 text-sm text-amber-700 dark:text-amber-400">{result.why_not}</p>
          </div>
        )}

        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
          {game.hltb_main != null && (
            <div>
              <dt className="text-muted-foreground">Length</dt>
              <dd>{Math.round(game.hltb_main)} hours</dd>
            </div>
          )}
          {game.story_gameplay_ratio != null && (
            <div>
              <dt className="text-muted-foreground">Story focus</dt>
              <dd>{Math.round(game.story_gameplay_ratio)}/100</dd>
            </div>
          )}
          {game.igdb_rating != null && (
            <div>
              <dt className="text-muted-foreground">Review score</dt>
              <dd>{Math.round(game.igdb_rating)}/100</dd>
            </div>
          )}
          {game.platforms.length > 0 && (
            <div className="col-span-2 sm:col-span-3">
              <dt className="text-muted-foreground">Platforms</dt>
              <dd>{game.platforms.join(", ")}</dd>
            </div>
          )}
        </dl>

        <div className="flex flex-wrap items-center gap-3 pt-2">
          <SignedIn>
            <SaveButton gameId={game.id} />
            <PlayedButton gameId={game.id} />
          </SignedIn>
          <SignedOut>
            <span className="text-sm text-muted-foreground">Sign in to save or exclude games</span>
          </SignedOut>
        </div>
      </div>
    </main>
  );
}
