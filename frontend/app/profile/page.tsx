"use client";

import { Suspense } from "react";
import { SignedIn, SignedOut } from "@clerk/nextjs";
import { BookUser } from "lucide-react";
import SteamImport from "@/components/SteamImport";
import OwnedPlatforms from "@/components/OwnedPlatforms";

export default function ProfilePage() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="flex items-center gap-2 font-heading text-2xl font-semibold tracking-tight">
        <BookUser className="size-6 text-primary" aria-hidden="true" />
        Profile
      </h1>

      <div className="mt-8 space-y-6">
        <SignedIn>
          <Suspense fallback={null}>
            <SteamImport />
          </Suspense>
          <OwnedPlatforms />
        </SignedIn>
        <SignedOut>
          <p className="text-sm text-muted-foreground">Sign in to manage your profile.</p>
        </SignedOut>
      </div>
    </main>
  );
}
