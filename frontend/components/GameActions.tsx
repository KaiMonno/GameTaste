"use client";

import { useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { Bookmark, BookOpenCheck, BookMarked } from "lucide-react";
import { addToWishlist, markAsPlayed, unmarkAsPlayed } from "@/lib/api";
import { Button } from "@/components/ui/button";

// Shared between the game detail page and (previously) the results list -
// kept as their own component since both "save to wishlist" and "mark
// played" are self-contained bits of state (idle/saving/saved/error) that
// don't need to know anything about where they're rendered.

export function SaveButton({ gameId }: { gameId: number }) {
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
    return (
      <span className="inline-flex items-center gap-1 text-sm text-muted-foreground">
        <BookMarked className="size-3.5" aria-hidden="true" />
        Saved to wishlist
      </span>
    );
  }

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={handleClick}
      disabled={state === "saving"}
      className="gap-1.5"
    >
      <Bookmark className="size-3.5" aria-hidden="true" />
      {state === "error" ? "Couldn't save - try again" : state === "saving" ? "Saving..." : "Save to wishlist"}
    </Button>
  );
}

export function PlayedButton({ gameId }: { gameId: number }) {
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
      <span className="inline-flex items-center gap-1 text-sm text-muted-foreground">
        <BookOpenCheck className="size-3.5" aria-hidden="true" />
        Won&apos;t be recommended again -{" "}
        <button type="button" onClick={handleUndo} className="underline hover:text-foreground">
          undo
        </button>
      </span>
    );
  }

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={handleClick}
      disabled={state === "marking"}
      className="gap-1.5"
    >
      <BookOpenCheck className="size-3.5" aria-hidden="true" />
      {state === "error" ? "Couldn't mark - try again" : state === "marking" ? "Marking..." : "Already played"}
    </Button>
  );
}
