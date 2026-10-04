import { auth } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";
import { STEAM_OPENID_ENDPOINT, callbackUrl } from "../shared";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
  // shape looks right. assoc_handle is checked for presence only, not a
  // specific value - an earlier version pinned it to a value taken from
  // one third-party reference implementation, which isn't something
  // Steam's protocol actually guarantees and isn't load-bearing for
  // security anyway (the check_authentication round trip below is what
  // actually proves authenticity, not this field's value).
  const claimedId = params.get("openid.claimed_id") ?? "";
  const identity = params.get("openid.identity") ?? "";
  const match = CLAIMED_ID_PATTERN.exec(claimedId);

  const checks = {
    ns: params.get("openid.ns") === "http://specs.openid.net/auth/2.0",
    mode: params.get("openid.mode") === "id_res",
    op_endpoint: params.get("openid.op_endpoint") === STEAM_OPENID_ENDPOINT,
    return_to: params.get("openid.return_to") === callbackUrl(origin),
    assoc_handle: !!params.get("openid.assoc_handle"),
    response_nonce: !!params.get("openid.response_nonce"),
    signed: !!params.get("openid.signed"),
    sig: !!params.get("openid.sig"),
    claimed_id_format: !!match,
    identity_matches_claimed_id: identity === claimedId,
  };

  if (!Object.values(checks).every(Boolean)) {
    console.error("[steam-openid] callback validation failed", {
      checks,
      received: Object.fromEntries(params),
      expected_return_to: callbackUrl(origin),
    });
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
    if (!isValid) {
      console.error("[steam-openid] check_authentication returned not-valid", { status: verifyResp.status, body });
    }
  } catch (err) {
    console.error("[steam-openid] check_authentication request failed", err);
    return errorRedirect(origin, "Couldn't verify with Steam - please try again");
  }

  if (!isValid) {
    return errorRedirect(origin, "Steam didn't confirm this sign-in - please try again");
  }

  // checks.claimed_id_format already confirmed `match` is non-null above,
  // but that's not visible to TS through the checks object indirection.
  const steamId64 = match![1];

  try {
    const token = await getToken();
    const importResp = await fetch(`${API_URL}/profile/steam-import`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ steam_identifier: steamId64 }),
    });

    if (!importResp.ok) {
      const errBody = await importResp.json().catch(() => null);
      console.error("[steam-openid] backend import failed", { status: importResp.status, errBody });
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
  } catch (err) {
    console.error("[steam-openid] request to backend import endpoint failed", err);
    return errorRedirect(origin, "Couldn't reach the import service - please try again");
  }
}
