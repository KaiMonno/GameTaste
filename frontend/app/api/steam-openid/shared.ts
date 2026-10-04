/** Shared between start/route.ts and callback/route.ts - both must build
 * these identically, since Steam echoes back openid.return_to and the
 * callback verifies it matches exactly (see callback/route.ts).
 *
 * No Steam-side registration needed for any of this - unlike a typical
 * OAuth app, OpenID 2.0 (what Steam uses) takes realm/return_to live in
 * each request rather than a pre-registered redirect URI.
 */
export const STEAM_OPENID_ENDPOINT = "https://steamcommunity.com/openid/login";

export function callbackUrl(origin: string): string {
  return `${origin}/api/steam-openid/callback`;
}
