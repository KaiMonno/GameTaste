import { clerkMiddleware } from "@clerk/nextjs/server";

// Runs on every request so useAuth()/auth() have session state available,
// but doesn't force sign-in anywhere - browsing and getting recommendations
// stay anonymous-friendly (see mvp-plan.md Phase 5); only wishlist/saved-
// preferences actions require a signed-in user, enforced by the backend
// (see backend/app/services/auth.py) rather than route-level redirects here.
export default clerkMiddleware();

export const config = {
  matcher: ["/((?!_next|.*\\..*).*)"],
};
