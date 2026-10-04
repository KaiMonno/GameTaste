import { auth } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";
import { STEAM_OPENID_ENDPOINT, callbackUrl } from "../shared";

/** Starts the "Sign in through Steam" flow - redirects the browser to
 * Steam's OpenID login page. Steam redirects back to callback/route.ts
 * once the user authenticates there.
 */
export async function GET(request: Request) {
  const { userId } = await auth();
  const origin = new URL(request.url).origin;

  if (!userId) {
    return NextResponse.redirect(`${origin}/`);
  }

  const params = new URLSearchParams({
    "openid.ns": "http://specs.openid.net/auth/2.0",
    "openid.mode": "checkid_setup",
    "openid.realm": `${origin}/`,
    "openid.return_to": callbackUrl(origin),
    // "identifier_select" - let Steam's login page pick which identity to
    // assert, rather than us pre-supplying one (we don't have it yet).
    "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
    "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
  });

  return NextResponse.redirect(`${STEAM_OPENID_ENDPOINT}?${params.toString()}`);
}
