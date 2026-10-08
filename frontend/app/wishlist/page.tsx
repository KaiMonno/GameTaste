"use client";

import { useEffect, useState } from "react";
import { useAuth, SignedIn, SignedOut } from "@clerk/nextjs";
import { getWishlist, removeFromWishlist, type WishlistItem } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Bookmark } from "lucide-react";

function WishlistContent() {
  const { getToken } = useAuth();
  const [items, setItems] = useState<WishlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const token = await getToken();
        setItems(await getWishlist(token));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load wishlist");
      } finally {
        setLoading(false);
      }
    })();
  }, [getToken]);

  async function handleRemove(gameId: number) {
    const token = await getToken();
    await removeFromWishlist(token, gameId);
    setItems((prev) => prev.filter((item) => item.game.id !== gameId));
  }

  if (loading) return <p className="text-sm text-muted-foreground">Loading...</p>;
  if (error)
    return (
      <Alert variant="destructive">
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  if (items.length === 0)
    return <p className="text-sm text-muted-foreground">Nothing saved yet - save a game from your results.</p>;

  return (
    <ul className="space-y-3">
      {items.map(({ game }) => (
        <li key={game.id}>
          <Card>
            <CardHeader>
              <div className="flex items-start justify-between gap-3">
                <CardTitle>{game.name}</CardTitle>
                <Button
                  type="button"
                  variant="link"
                  size="sm"
                  onClick={() => handleRemove(game.id)}
                  className="h-auto shrink-0 p-0 text-muted-foreground"
                >
                  Remove
                </Button>
              </div>
            </CardHeader>
            {game.summary && (
              <CardContent>
                <p className="text-sm text-muted-foreground line-clamp-2">{game.summary}</p>
              </CardContent>
            )}
          </Card>
        </li>
      ))}
    </ul>
  );
}

export default function WishlistPage() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="flex items-center gap-2 font-heading text-2xl font-semibold tracking-tight">
        <Bookmark className="size-6 text-primary" aria-hidden="true" />
        Your wishlist
      </h1>

      <div className="mt-8">
        <SignedIn>
          <WishlistContent />
        </SignedIn>
        <SignedOut>
          <p className="text-sm text-muted-foreground">Sign in to see games you&apos;ve saved.</p>
        </SignedOut>
      </div>
    </main>
  );
}
