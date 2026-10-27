"""Supabase client and raw data access.

This module only shapes requests/responses. It does not decide who is
allowed to do what — Supabase RLS (sql/schema.sql) is the actual
authorization boundary, and every write here will be rejected by the
database itself if the caller's session isn't an allowlisted editor,
regardless of what the UI shows.

The client is stored in st.session_state (per browser session), never in
a shared st.cache_resource — a cached global client would let one
visitor's auth token leak into another visitor's requests.
"""
from __future__ import annotations

import os

import streamlit as st
from postgrest.exceptions import APIError
from supabase import Client, create_client

UNIQUE_VIOLATION = "23505"


class DatabaseError(RuntimeError):
    """A request to Supabase failed in a way the UI should show to the user."""


class DuplicatePlayerError(DatabaseError):
    """Raised when a player name collides with an existing normalized_name."""


def _get_secret(key: str) -> str | None:
    try:
        value = st.secrets.get(key)
    except Exception:
        value = None
    value = value or os.environ.get(key)
    if not value:
        return None
    # Supabase URLs and anon keys are always plain ASCII. Strip anything else
    # defensively — e.g. smart quotes or other invisible characters a web
    # form's autocorrect can introduce when a secret is pasted in — rather
    # than fail deep inside httpx with a cryptic UnicodeEncodeError.
    return value.strip().encode("ascii", "ignore").decode("ascii") or None


def get_client() -> Client:
    if "_sb_client" not in st.session_state:
        url = _get_secret("SUPABASE_URL")
        anon_key = _get_secret("SUPABASE_ANON_KEY")
        if not url or not anon_key:
            raise DatabaseError(
                "Missing SUPABASE_URL / SUPABASE_ANON_KEY. Set them in "
                ".streamlit/secrets.toml (see secrets.toml.example) or as "
                "environment variables."
            )
        st.session_state["_sb_client"] = create_client(url, anon_key)
    return st.session_state["_sb_client"]


def is_auth_error(exc: Exception) -> bool:
    message = (getattr(exc, "message", None) or str(exc)).lower()
    return "jwt" in message or "expired" in message or "invalid refresh token" in message


def _friendly_db_error(exc: Exception) -> str:
    if is_auth_error(exc):
        return "Your session has expired. Please sign in again."
    return "Database request failed. Please try again."


def fetch_player_totals(include_inactive: bool = False) -> list[dict]:
    client = get_client()
    query = client.table("player_totals").select("*")
    if not include_inactive:
        query = query.eq("active", True)
    try:
        response = query.execute()
    except Exception as exc:  # noqa: BLE001 - boundary call, translate for the UI
        raise DatabaseError(_friendly_db_error(exc)) from exc
    return response.data


def insert_player(name: str) -> str:
    client = get_client()
    try:
        response = client.table("players").insert({"name": name}).execute()
    except APIError as exc:
        if exc.code == UNIQUE_VIOLATION:
            raise DuplicatePlayerError(f'"{name}" is already on the roster.') from exc
        raise DatabaseError(_friendly_db_error(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise DatabaseError(_friendly_db_error(exc)) from exc
    return response.data[0]["id"]


def update_player_name(player_id: str, new_name: str) -> None:
    client = get_client()
    try:
        client.table("players").update({"name": new_name}).eq("id", player_id).execute()
    except APIError as exc:
        if exc.code == UNIQUE_VIOLATION:
            raise DuplicatePlayerError(f'"{new_name}" is already on the roster.') from exc
        raise DatabaseError(_friendly_db_error(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise DatabaseError(_friendly_db_error(exc)) from exc


def update_player_active(player_id: str, active: bool) -> None:
    client = get_client()
    try:
        client.table("players").update({"active": active}).eq("id", player_id).execute()
    except Exception as exc:  # noqa: BLE001
        raise DatabaseError(_friendly_db_error(exc)) from exc


def insert_point_event(player_id: str, category: str) -> str:
    client = get_client()
    try:
        response = (
            client.table("point_events")
            .insert({"player_id": player_id, "category": category})
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise DatabaseError(_friendly_db_error(exc)) from exc
    return response.data[0]["id"]


def delete_point_event_by_id(event_id: str) -> bool:
    client = get_client()
    try:
        response = client.table("point_events").delete().eq("id", event_id).execute()
    except Exception as exc:  # noqa: BLE001
        raise DatabaseError(_friendly_db_error(exc)) from exc
    return bool(response.data)


def delete_latest_point_event(player_id: str, category: str) -> bool:
    client = get_client()
    try:
        latest = (
            client.table("point_events")
            .select("id")
            .eq("player_id", player_id)
            .eq("category", category)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise DatabaseError(_friendly_db_error(exc)) from exc

    if not latest.data:
        return False
    return delete_point_event_by_id(latest.data[0]["id"])


def call_award_team_win() -> int:
    client = get_client()
    try:
        response = client.rpc("award_team_win", {}).execute()
    except Exception as exc:  # noqa: BLE001
        raise DatabaseError(_friendly_db_error(exc)) from exc
    return int(response.data or 0)


def fetch_recent_activity(limit: int = 20) -> list[dict]:
    client = get_client()
    try:
        response = (
            client.table("point_events")
            .select("id, category, created_at, player:players(name)")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise DatabaseError(_friendly_db_error(exc)) from exc

    activity = []
    for row in response.data:
        player = row.get("player") or {}
        activity.append(
            {
                "id": row["id"],
                "category": row["category"],
                "created_at": row["created_at"],
                "player_name": player.get("name", "Unknown player"),
            }
        )
    return activity


def check_is_approved_editor() -> bool:
    client = get_client()
    try:
        response = client.rpc("is_approved_editor", {}).execute()
    except Exception as exc:  # noqa: BLE001
        raise DatabaseError(_friendly_db_error(exc)) from exc
    return bool(response.data)
