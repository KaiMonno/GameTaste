"""Phase 5: verifies the Clerk session token attached to each authenticated
request. Clerk owns identity/sessions entirely - this module never sees a
password, only extracts and verifies the signed token Clerk's frontend SDK
attaches (Authorization: Bearer <token>, or the __session cookie), via
Clerk's own official SDK rather than hand-rolled JWT/JWKS handling.
"""

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import User

try:
    from clerk_backend_api import AuthenticateRequestOptions, Clerk
except ImportError:  # pragma: no cover - see requirements.txt, installed for Phase 5
    AuthenticateRequestOptions = None
    Clerk = None


def _authorized_parties() -> list[str]:
    raw = get_settings().clerk_authorized_parties
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


async def get_current_clerk_user_id(request: Request) -> str:
    """Verifies the request's Clerk session token and returns the Clerk
    user id (the `sub` claim). Raises 401 on a missing/invalid/expired
    token - callers that need an app-level User row should depend on
    get_current_user instead, which builds on this.
    """
    settings = get_settings()
    if not settings.clerk_secret_key:
        raise HTTPException(status_code=500, detail="Server is not configured for authentication")

    clerk = Clerk(bearer_auth=settings.clerk_secret_key)
    state = await clerk.authenticate_request_async(
        request,
        AuthenticateRequestOptions(
            secret_key=settings.clerk_secret_key,
            jwt_key=settings.clerk_jwt_key or None,
            authorized_parties=_authorized_parties(),
        ),
    )

    if not state.is_signed_in or not state.payload:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = state.payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return user_id


async def get_current_user(
    clerk_user_id: str = Depends(get_current_clerk_user_id),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Get-or-create the app-level User row mirroring this Clerk identity.
    Lazy creation on first authenticated request, rather than a Clerk
    webhook-driven sync - simpler, and the only thing we need this row for
    is a stable FK target for preferences/wishlist.
    """
    result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
    user = result.scalar_one_or_none()
    if user is not None:
        return user

    user = User(clerk_user_id=clerk_user_id)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        # Two concurrent first-requests from the same new user (e.g. two
        # tabs loading at once) both lose the SELECT race - the loser just
        # re-fetches the row the winner created instead of erroring.
        await db.rollback()
        result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
        return result.scalar_one()
    await db.refresh(user)
    return user


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Phase 6: like get_current_user, but None instead of a 401 when
    there's no/an invalid token - for endpoints that must stay usable
    signed-out (routers/recommendations.py excludes a signed-in user's
    Steam library from results, but anonymous search is still the default
    experience, not an error case).
    """
    settings = get_settings()
    if not settings.clerk_secret_key:
        return None
    try:
        clerk_user_id = await get_current_clerk_user_id(request)
    except HTTPException:
        return None
    return await get_current_user(clerk_user_id, db)
