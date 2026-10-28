"""Sign-in, sign-out, and editor-role checks.

Streamlit holds only the signed-in user's tokens, in st.session_state.
It is never the source of truth for whether a write is allowed — that's
decided by Supabase RLS via the editor_allowlist table (see
sql/schema.sql and database.check_is_approved_editor, which calls the
is_approved_editor() RPC rather than reading the allowlist directly,
since ordinary users have no SELECT grant on it at all).
"""
from __future__ import annotations

import streamlit as st

import database
from database import DatabaseError, get_client


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
