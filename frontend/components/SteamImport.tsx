"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { getSteamStatus, importSteamLibrary, type SteamImportResult, type SteamStatus } from "@/lib/api";

/** The single source of truth for "is Steam linked" is the backend
 * (GET /profile/steam-status), not a one-time toast tied to how the user
 * got here - a toast is easy to miss, and clearing it from the URL after
 * the OpenID redirect (see app/api/steam-openid/callback/route.ts) turned
 * out to be unreliable on its own. Both the manual-paste form below and
 * the OpenID redirect end up back on THIS component, which re-fetches
 * status either way, so "linked" always reflects what's actually stored.
 */
export default function SteamImport() {
  const { getToken } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [status, setStatus] = useState<SteamStatus | null>(null);
  const [steamIdentifier, setSteamIdentifier] = useState("");
  const [state, setState] = useState<"idle" | "importing" | "done" | "error">("idle");
  const [result, setResult] = useState<SteamImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      const token = await getToken();
      setStatus(await getSteamStatus(token));
    } catch {
      // Status is informational - if it fails to load, the form below
      // still works, it just can't show the "already linked" banner.
    }
  }, [getToken]);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  // Picks up the ?steam=success|error the OpenID callback redirects back
  // to, shows it once, then strips it from the URL and re-checks status -
  // the status check (not the URL param surviving) is what the "linked"
  // banner below actually depends on.
  useEffect(() => {
    const steamResult = searchParams.get("steam");
    if (!steamResult) return;

    if (steamResult === "error") {
      setError(searchParams.get("message") ?? "Something went wrong signing in with Steam");
      setState("error");
    } else {
      refreshStatus();
    }
    // Strips the ?steam=... params without navigating away - this
    // component doesn't assume which page it's mounted on (previously
    // hardcoded to "/", which silently redirected away from /profile once
    // SteamImport moved there - see the Phase 6 profile-tab commit).
    router.replace(pathname, { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  async function handleImport(e: React.FormEvent) {
    e.preventDefault();
    if (!steamIdentifier.trim()) return;

    setState("importing");
    setError(null);
    try {
      const token = await getToken();
      const res = await importSteamLibrary(token, steamIdentifier.trim());
      setResult(res);
      setState("done");
      await refreshStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
      setState("error");
    }
  }

  return (
    <div className="rounded border border-gray-200 bg-white p-4">
      <h2 className="font-semibold">Steam library</h2>

      {status?.linked && (
        <p className="mt-1 text-sm text-green-700">
          ✓ Linked - {status.game_count} owned game{status.game_count === 1 ? "" : "s"} excluded from your
          recommendations
          {status.last_synced_at ? ` (last synced ${new Date(status.last_synced_at).toLocaleString()})` : ""}.
        </p>
      )}

      <p className="mt-1 text-sm text-gray-600">
        {status?.linked
          ? "Re-sync any time to pick up newly bought or removed games."
          : "Games you already own won't show up in your recommendations. Your Steam profile and game details need to be set to Public."}
      </p>

      <a
        href="/api/steam-openid/start"
        className="mt-3 inline-block rounded bg-[#1b2838] px-4 py-2 text-sm text-white hover:bg-[#2a3f5a]"
      >
        {status?.linked ? "Re-sync with Steam" : "Sign in through Steam"}
      </a>

      <div className="my-3 flex items-center gap-2 text-xs text-gray-400">
        <div className="h-px flex-1 bg-gray-200" />
        or paste it manually
        <div className="h-px flex-1 bg-gray-200" />
      </div>

      <form onSubmit={handleImport} className="flex gap-2">
        <input
          type="text"
          value={steamIdentifier}
          onChange={(e) => setSteamIdentifier(e.target.value)}
          placeholder="Profile URL, vanity name, or SteamID64"
          className="flex-1 rounded border border-gray-300 px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={state === "importing"}
          className="rounded bg-gray-900 px-4 py-2 text-sm text-white disabled:opacity-50"
        >
          {state === "importing" ? "Importing..." : "Import"}
        </button>
      </form>

      {state === "done" && result && (
        <p className="mt-2 text-sm text-green-700">
          Found {result.total_owned} owned games - {result.matched} will be excluded from your
          recommendations{result.unmatched > 0 ? ` (${result.unmatched} aren't in our catalog)` : ""}.
        </p>
      )}
      {state === "error" && error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </div>
  );
}
