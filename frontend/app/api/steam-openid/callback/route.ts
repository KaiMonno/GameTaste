import { auth } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";
import { STEAM_OPENID_ENDPOINT, callbackUrl } from "../shared";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Steam's OpenID assertions are unsigned-discovery/"dumb mode" - it always
// echoes this exact dummy assoc_handle rather than a real per-request one
// (confirmed against a known-working reference implementation, not
// guessed - see the Phase 6 OpenID commit message for the source).
const STEAM_DUMMY_ASSOC_HANDLE = "1234567890";

const CLAIMED_ID_PATTERN = /^https:\/\/steamcommunity\.com\/openid\/id\/(\d{1,20})$/;

function errorRedirect(origin: string, message: string): NextResponse {
  return NextResponse.redirect(`${origin}/?steam=error&message=${encodeURIComponent(message)}`);
}

/** Verifies Steam's OpenID callback and, on success, feeds the resulting
 * SteamID64 into the existing POST /profile/steam-import endpoint (which
 * already accepts a bare SteamID64 directly - see
 * backend/app/services/steam_client.py resolve_steam_id64). No backend
 * changes needed for this flow; it only produces a verified identifier
 * for an endpoint that already existed.
 */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const origin = url.origin;
  const params = url.searchParams;

  const { userId, getToken } = await auth();
  if (!userId) {
    return errorRedirect(origin, "You must be signed in to link a Steam account");
  }

  if (params.get("openid.mode") === "cancel") {
    return NextResponse.redirect(`${origin}/`);
  }

  // Validate every security-relevant field BEFORE trusting anything in
  // the response, and before spending a network call on it - never trust
  // claimed_id/identity without the check_authentication round trip below,
  // which is what actually proves Steam signed this, not just that the
  // shape looks right.
  const claimedId = params.get("openid.claimed_id") ?? "";
  const identity = params.get("openid.identity") ?? "";
  const match = CLAIMED_ID_PATTERN.exec(claimedId);

  const isWellFormed =
    params.get("openid.ns") === "http://specs.openid.net/auth/2.0" &&
    params.get("openid.mode") === "id_res" &&
    params.get("openid.op_endpoint") === STEAM_OPENID_ENDPOINT &&
    params.get("openid.return_to") === callbackUrl(origin) &&
    params.get("openid.assoc_handle") === STEAM_DUMMY_ASSOC_HANDLE &&
    !!params.get("openid.response_nonce") &&
    !!params.get("openid.signed") &&
    !!params.get("openid.sig") &&
    !!match &&
    identity === claimedId;

  if (!isWellFormed) {
    return errorRedirect(origin, "Steam's response didn't look right - please try again");
  }

  // The actual proof: copy every received param back to Steam with mode
  // switched to check_authentication, and only trust is_valid:true in
  // Steam's response - never the op_endpoint echoed in the original
  // callback (that's attacker-controlled input, not verified yet at this
  // point), always this fixed, hardcoded endpoint.
  const verifyParams = new URLSearchParams(params);
  verifyParams.set("openid.mode", "check_authentication");

  let isValid = false;
  try {
    const verifyResp = await fetch(`${STEAM_OPENID_ENDPOINT}?${verifyParams.toString()}`, { method: "POST" });
    const body = await verifyResp.text();
    const fields = Object.fromEntries(
      body
        .split("\n")
        .map((line) => line.split(":"))
        .filter((parts) => parts.length >= 2)
        .map(([key, ...rest]) => [key, rest.join(":")])
    );
    isValid = fields.ns === "http://specs.openid.net/auth/2.0" && fields.is_valid === "true";
  } catch {
    return errorRedirect(origin, "Couldn't verify with Steam - please try again");
  }

  if (!isValid) {
    return errorRedirect(origin, "Steam didn't confirm this sign-in - please try again");
  }

  const steamId64 = match[1];

  try {
    const token = await getToken();
    const importResp = await fetch(`${API_URL}/profile/steam-import`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ steam_identifier: steamId64 }),
    });

    if (!importResp.ok) {
      const errBody = await importResp.json().catch(() => null);
      return errorRedirect(origin, errBody?.detail ?? `Import failed: ${importResp.status}`);
    }

    const result = await importResp.json();
    const qs = new URLSearchParams({
      steam: "success",
      total: String(result.total_owned),
      matched: String(result.matched),
      unmatched: String(result.unmatched),
    });
    return NextResponse.redirect(`${origin}/?${qs.toString()}`);
  } catch {
    return errorRedirect(origin, "Couldn't reach the import service - please try again");
  }
}
