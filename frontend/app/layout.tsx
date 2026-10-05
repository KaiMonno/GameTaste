import type { Metadata } from "next";
import Link from "next/link";
import { ClerkProvider, SignedIn, SignedOut, SignInButton, UserButton } from "@clerk/nextjs";
import "./globals.css";

export const metadata: Metadata = {
  title: "GameTaste",
  description: "AI-powered game recommendations",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <html lang="en">
        <body className="bg-gray-50 text-gray-900">
          <header className="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-3">
            <Link href="/" className="font-semibold">
              GameTaste
            </Link>
            <div className="flex items-center gap-4">
              <SignedIn>
                <Link href="/wishlist" className="text-sm text-gray-600 hover:text-gray-900">
                  Wishlist
                </Link>
                <Link href="/profile" className="text-sm text-gray-600 hover:text-gray-900">
                  Profile
                </Link>
                <UserButton afterSignOutUrl="/" />
              </SignedIn>
              <SignedOut>
                <SignInButton mode="modal">
                  <button className="rounded bg-gray-900 px-3 py-1.5 text-sm text-white">Sign in</button>
                </SignInButton>
              </SignedOut>
            </div>
          </header>
          {children}
        </body>
      </html>
    </ClerkProvider>
  );
}
