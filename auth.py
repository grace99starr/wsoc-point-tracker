"""Sign-in, sign-out, and editor-role checks.

Streamlit holds only the signed-in user's tokens, in st.session_state.
It is never the source of truth for whether a write is allowed — that's
decided by Supabase RLS via the editor_allowlist table (see
sql/schema.sql and database.check_is_approved_editor, which calls the
is_approved_editor() RPC rather than reading the allowlist directly,
since ordinary users have no SELECT grant on it at all).

Staying signed in across visits is layered on top of that: a Supabase
refresh token is persisted in a browser cookie (via a tiny injected
script — no extra dependency) so restore_session() can silently rebuild
a session on a later visit without the user retyping credentials. That
cookie is a real bearer credential for the lifetime it's valid, same
tradeoff as any "remember me" feature — anyone with access to that
specific browser could act as that editor without the password, until
they log out or the cookie expires/rotates out.
"""
from __future__ import annotations

import json

import streamlit as st
import streamlit.components.v1 as components

import database
from database import DatabaseError, get_client

_REFRESH_COOKIE_NAME = "wsoc_refresh_token"
_REFRESH_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days


def _set_refresh_cookie(token: str) -> None:
    components.html(
        f"""
        <script>
        const secure = (window.location.protocol === "https:") ? "Secure;" : "";
        document.cookie = {json.dumps(_REFRESH_COOKIE_NAME)} + "="
            + encodeURIComponent({json.dumps(token)})
            + "; path=/; max-age={_REFRESH_COOKIE_MAX_AGE_SECONDS}; SameSite=Lax; " + secure;
        </script>
        """,
        height=0,
    )


def _clear_refresh_cookie() -> None:
    components.html(
        f"""
        <script>
        document.cookie = {json.dumps(_REFRESH_COOKIE_NAME)} + "=; path=/; max-age=0; SameSite=Lax";
        </script>
        """,
        height=0,
    )


def restore_session() -> None:
    """Silently rebuild a signed-in session from a persisted refresh-token
    cookie, if one exists and is still valid. Call once near the top of
    the app, before anything checks is_signed_in()/is_approved_editor().
    """
    if is_signed_in():
        return
    try:
        token = st.context.cookies.get(_REFRESH_COOKIE_NAME)
    except Exception:  # noqa: BLE001 - cookie access should never crash the app
        token = None
    if not token:
        return

    client = get_client()
    try:
        result = client.auth.refresh_session(token)
    except Exception as exc:  # noqa: BLE001 - expired/revoked/invalid token: fall back to signed-out
        import sys
        print(f"[DEBUG] restore_session refresh failed: token_len={len(token)} error={exc!r}", file=sys.stderr)
        _clear_refresh_cookie()
        return

    if result.session is None or result.user is None:
        import sys
        print(f"[DEBUG] restore_session got empty session/user: {result!r}", file=sys.stderr)
        _clear_refresh_cookie()
        return

    client.postgrest.auth(result.session.access_token)
    st.session_state["auth_user_id"] = result.user.id
    st.session_state["auth_email"] = result.user.email
    st.session_state.pop("is_editor_cache", None)
    # Supabase rotates the refresh token on each use — the old cookie value
    # is now invalid, so persist the new one or the next visit's restore
    # attempt will silently fail.
    _set_refresh_cookie(result.session.refresh_token)


def sign_in(email: str, password: str) -> tuple[bool, str]:
    client = get_client()
    try:
        result = client.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as exc:  # noqa: BLE001 - any auth failure becomes a user-facing message
        return False, _friendly_auth_error(exc)

    if result.session is None or result.user is None:
        return False, "Sign-in failed. Check your email and password."

    client.postgrest.auth(result.session.access_token)
    st.session_state["auth_user_id"] = result.user.id
    st.session_state["auth_email"] = result.user.email
    st.session_state.pop("is_editor_cache", None)
    _set_refresh_cookie(result.session.refresh_token)
    return True, ""


def sign_out() -> None:
    client = get_client()
    try:
        client.auth.sign_out()
    except Exception:  # noqa: BLE001 - sign-out is best-effort cleanup
        pass
    # postgrest's .auth(None) raises (it requires an actual token or
    # basic-auth credentials) rather than clearing the header, so instead
    # drop the cached client entirely — the next get_client() call builds a
    # brand new anonymous one with no leftover Authorization header at all.
    st.session_state.pop("_sb_client", None)
    for key in ("auth_user_id", "auth_email", "is_editor_cache"):
        st.session_state.pop(key, None)
    _clear_refresh_cookie()


def is_signed_in() -> bool:
    return bool(st.session_state.get("auth_user_id"))


def current_user_email() -> str | None:
    return st.session_state.get("auth_email")


def is_approved_editor() -> bool:
    """True only if signed in AND present in editor_allowlist.

    Cached for the lifetime of the browser session so every rerun doesn't
    re-check; cleared on sign-in/sign-out. If the check itself fails
    (expired session, network issue), fail closed to read-only.
    """
    if not is_signed_in():
        return False
    if "is_editor_cache" in st.session_state:
        return st.session_state["is_editor_cache"]

    try:
        approved = database.check_is_approved_editor()
    except DatabaseError:
        sign_out()
        return False

    st.session_state["is_editor_cache"] = approved
    return approved


def _friendly_auth_error(exc: Exception) -> str:
    message = str(exc)
    if "Invalid login credentials" in message:
        return "Invalid email or password."
    return "Sign-in failed. Please try again."
