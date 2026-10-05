"use client";

import { useState } from "react";
import { SignedIn, SignedOut, useAuth } from "@clerk/nextjs";
import { addToWishlist, markAsPlayed, unmarkAsPlayed, type RecommendationResult } from "@/lib/api";

function SaveButton({ gameId }: { gameId: number }) {
  const { getToken } = useAuth();
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");

  async function handleClick() {
    setState("saving");
    try {
      const token = await getToken();
      await addToWishlist(token, gameId);
      setState("saved");
    } catch {
      setState("error");
    }
  }

  if (state === "saved") {
    return <span className="text-sm text-gray-500">Saved to wishlist</span>;
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={state === "saving"}
      className="text-sm text-gray-600 underline hover:text-gray-900 disabled:opacity-50"
    >
      {state === "error" ? "Couldn't save - try again" : state === "saving" ? "Saving..." : "Save to wishlist"}
    </button>
  );
}

function PlayedButton({ gameId }: { gameId: number }) {
  const { getToken } = useAuth();
  const [state, setState] = useState<"idle" | "marking" | "marked" | "error">("idle");

  async function handleClick() {
    setState("marking");
    try {
      const token = await getToken();
      await markAsPlayed(token, gameId);
      setState("marked");
    } catch {
      setState("error");
    }
  }

  async function handleUndo() {
    try {
      const token = await getToken();
      await unmarkAsPlayed(token, gameId);
      setState("idle");
    } catch {
      // Leave it marked if undo fails - understating is safer than
      // silently dropping an exclusion the user thinks is still in place.
    }
  }

  if (state === "marked") {
    return (
      <span className="text-sm text-gray-500">
        Won&apos;t be recommended again -{" "}
        <button type="button" onClick={handleUndo} className="underline hover:text-gray-900">
          undo
        </button>
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={state === "marking"}
      className="text-sm text-gray-600 underline hover:text-gray-900 disabled:opacity-50"
    >
      {state === "error" ? "Couldn't mark - try again" : state === "marking" ? "Marking..." : "Already played"}
    </button>
  );
}

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

          <div className="mt-2 flex flex-wrap items-center gap-3">
            <SignedIn>
              <SaveButton gameId={r.game.id} />
              <PlayedButton gameId={r.game.id} />
            </SignedIn>
            <SignedOut>
              <span className="text-sm text-gray-400">Sign in to save or exclude games</span>
            </SignedOut>
          </div>
        </li>
      ))}
    </ul>
  );
}
