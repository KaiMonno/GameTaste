"use client";

import { Suspense } from "react";
import { SignedIn, SignedOut } from "@clerk/nextjs";
import SteamImport from "@/components/SteamImport";
import OwnedPlatforms from "@/components/OwnedPlatforms";

export default function ProfilePage() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="text-2xl font-bold">Profile</h1>

      <div className="mt-8 space-y-6">
        <SignedIn>
          <Suspense fallback={null}>
            <SteamImport />
          </Suspense>
          <OwnedPlatforms />
        </SignedIn>
        <SignedOut>
          <p className="text-gray-500">Sign in to manage your profile.</p>
        </SignedOut>
      </div>
    </main>
  );
}
