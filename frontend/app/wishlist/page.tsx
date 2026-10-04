"use client";

import { useEffect, useState } from "react";
import { useAuth, SignedIn, SignedOut } from "@clerk/nextjs";
import { getWishlist, removeFromWishlist, type WishlistItem } from "@/lib/api";

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

  if (loading) return <p className="text-gray-500">Loading...</p>;
  if (error) return <p className="text-red-600">{error}</p>;
  if (items.length === 0) return <p className="text-gray-500">Nothing saved yet - save a game from your results.</p>;

  return (
    <ul className="space-y-3">
      {items.map(({ game }) => (
        <li key={game.id} className="flex items-start justify-between rounded border border-gray-200 bg-white p-4">
          <div>
            <h3 className="font-semibold">{game.name}</h3>
            {game.summary && <p className="mt-1 text-sm text-gray-600 line-clamp-2">{game.summary}</p>}
          </div>
          <button
            type="button"
            onClick={() => handleRemove(game.id)}
            className="shrink-0 text-sm text-gray-500 underline hover:text-gray-900"
          >
            Remove
          </button>
        </li>
      ))}
    </ul>
  );
}

export default function WishlistPage() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="text-2xl font-bold">Your wishlist</h1>

      <div className="mt-8">
        <SignedIn>
          <WishlistContent />
        </SignedIn>
        <SignedOut>
          <p className="text-gray-500">Sign in to see games you've saved.</p>
        </SignedOut>
      </div>
    </main>
  );
}
