"""Tests for services/auth.py's optional-auth path (get_current_user_optional),
used by /recommendations to stay anonymous-friendly (see routers/
recommendations.py). get_current_user/get_current_clerk_user_id - the
required-auth path used everywhere else - are exercised indirectly by
test_profile_wishlist.py and test_steam_import.py, which pass a real User
in directly rather than a real Clerk token; this file is specifically
about what get_current_user_optional does when verification itself goes
wrong, which those don't cover.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.services import auth as auth_module


async def test_optional_auth_returns_none_on_401(monkeypatch):
    """The ordinary signed-out case: no/invalid token raises 401 from
    get_current_clerk_user_id - must become None, not propagate.
    """
    monkeypatch.setattr(auth_module.get_settings(), "clerk_secret_key", "sk_test_dummy")
    monkeypatch.setattr(
        auth_module, "get_current_clerk_user_id", AsyncMock(side_effect=HTTPException(status_code=401))
    )

    user = await auth_module.get_current_user_optional(request=object(), db=object())
    assert user is None


async def test_optional_auth_returns_none_on_unexpected_error(monkeypatch):
    """The bug this test locks in: Clerk verification currently makes a
    live network call (no networkless jwt_key configured), so a
    transient failure there (timeout, DNS, Clerk-side outage, ...) must
    degrade to "treat as signed out", not turn an otherwise-fine
    anonymous-friendly search into a 500. An earlier version only caught
    HTTPException here and would have let this propagate.
    """
    monkeypatch.setattr(auth_module.get_settings(), "clerk_secret_key", "sk_test_dummy")
    monkeypatch.setattr(
        auth_module, "get_current_clerk_user_id", AsyncMock(side_effect=RuntimeError("Clerk is unreachable"))
    )

    user = await auth_module.get_current_user_optional(request=object(), db=object())
    assert user is None


async def test_optional_auth_returns_none_when_not_configured(monkeypatch):
    monkeypatch.setattr(auth_module.get_settings(), "clerk_secret_key", "")

    user = await auth_module.get_current_user_optional(request=object(), db=object())
    assert user is None


async def test_optional_auth_returns_user_on_success(monkeypatch):
    monkeypatch.setattr(auth_module.get_settings(), "clerk_secret_key", "sk_test_dummy")
    monkeypatch.setattr(auth_module, "get_current_clerk_user_id", AsyncMock(return_value="clerk_abc"))
    sentinel_user = object()
    monkeypatch.setattr(auth_module, "get_current_user", AsyncMock(return_value=sentinel_user))

    user = await auth_module.get_current_user_optional(request=object(), db=object())
    assert user is sentinel_user
