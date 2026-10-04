"use client";

import { useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { importSteamLibrary, type SteamImportResult } from "@/lib/api";

export default function SteamImport() {
  const { getToken } = useAuth();
  const [steamIdentifier, setSteamIdentifier] = useState("");
  const [state, setState] = useState<"idle" | "importing" | "done" | "error">("idle");
  const [result, setResult] = useState<SteamImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
      setState("error");
    }
  }

  return (
    <div className="rounded border border-gray-200 bg-white p-4">
      <h2 className="font-semibold">Import your Steam library</h2>
      <p className="mt-1 text-sm text-gray-600">
        Games you already own won&apos;t show up in your recommendations. Your Steam profile and
        game details need to be set to Public.
      </p>

      <form onSubmit={handleImport} className="mt-3 flex gap-2">
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
