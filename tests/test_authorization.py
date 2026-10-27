"""Authorization / RLS integration tests.

These call the Supabase REST API directly over HTTP, bypassing the
Streamlit app entirely — the point is to prove the *database* rejects
unauthorized writes, not that the UI hides buttons nicely.

They need a dedicated TEST Supabase project (never point them at your
real team's data — they insert and delete real rows). Set:

    SUPABASE_TEST_URL
    SUPABASE_TEST_ANON_KEY
    SUPABASE_TEST_EDITOR_EMAIL          (an auth user already in editor_allowlist)
    SUPABASE_TEST_EDITOR_PASSWORD
    SUPABASE_TEST_NON_EDITOR_EMAIL      (a valid auth user, NOT in editor_allowlist)
    SUPABASE_TEST_NON_EDITOR_PASSWORD

Without all of those set, this whole module is skipped. See the README's
"Running tests and checking RLS security" section for a manual checklist
covering the same ground (plus things that don't automate well, like
two browsers and session expiry).
"""
from __future__ import annotations

import os

import httpx
import pytest

_REQUIRED_ENV = (
    "SUPABASE_TEST_URL",
    "SUPABASE_TEST_ANON_KEY",
    "SUPABASE_TEST_EDITOR_EMAIL",
    "SUPABASE_TEST_EDITOR_PASSWORD",
    "SUPABASE_TEST_NON_EDITOR_EMAIL",
    "SUPABASE_TEST_NON_EDITOR_PASSWORD",
)

pytestmark = pytest.mark.skipif(
    not all(os.environ.get(key) for key in _REQUIRED_ENV),
    reason="Dedicated test Supabase project not configured — set " + ", ".join(_REQUIRED_ENV),
)


@pytest.fixture(scope="module")
def base_url() -> str:
    return os.environ["SUPABASE_TEST_URL"].rstrip("/")


@pytest.fixture(scope="module")
def anon_key() -> str:
    return os.environ["SUPABASE_TEST_ANON_KEY"]


def _access_token(base_url: str, anon_key: str, email: str, password: str) -> str:
    response = httpx.post(
        f"{base_url}/auth/v1/token?grant_type=password",
        headers={"apikey": anon_key, "Content-Type": "application/json"},
        json={"email": email, "password": password},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def editor_token(base_url, anon_key) -> str:
    return _access_token(
        base_url,
        anon_key,
        os.environ["SUPABASE_TEST_EDITOR_EMAIL"],
        os.environ["SUPABASE_TEST_EDITOR_PASSWORD"],
    )


@pytest.fixture(scope="module")
def non_editor_token(base_url, anon_key) -> str:
    return _access_token(
        base_url,
        anon_key,
        os.environ["SUPABASE_TEST_NON_EDITOR_EMAIL"],
        os.environ["SUPABASE_TEST_NON_EDITOR_PASSWORD"],
    )


def test_anonymous_can_read_players(base_url, anon_key):
    response = httpx.get(f"{base_url}/rest/v1/players", headers={"apikey": anon_key}, timeout=10)
    assert response.status_code == 200


def test_anonymous_insert_is_rejected(base_url, anon_key):
    response = httpx.post(
        f"{base_url}/rest/v1/players",
        headers={"apikey": anon_key, "Content-Type": "application/json"},
        json={"name": "Should Not Exist"},
        timeout=10,
    )
    assert response.status_code in (401, 403)


def test_signed_in_non_editor_insert_is_rejected(base_url, anon_key, non_editor_token):
    response = httpx.post(
        f"{base_url}/rest/v1/players",
        headers={
            "apikey": anon_key,
            "Authorization": f"Bearer {non_editor_token}",
            "Content-Type": "application/json",
        },
        json={"name": "Should Not Exist Either"},
        timeout=10,
    )
    assert response.status_code in (401, 403)


def test_non_editor_cannot_read_allowlist(base_url, anon_key, non_editor_token):
    response = httpx.get(
        f"{base_url}/rest/v1/editor_allowlist",
        headers={"apikey": anon_key, "Authorization": f"Bearer {non_editor_token}"},
        timeout=10,
    )
    assert response.status_code == 200
    assert response.json() == []  # not even their own row is visible


def test_non_editor_cannot_self_allowlist(base_url, anon_key, non_editor_token):
    response = httpx.post(
        f"{base_url}/rest/v1/editor_allowlist",
        headers={
            "apikey": anon_key,
            "Authorization": f"Bearer {non_editor_token}",
            "Content-Type": "application/json",
        },
        json={"user_id": "00000000-0000-0000-0000-000000000000"},
        timeout=10,
    )
    assert response.status_code in (401, 403)


def test_non_editor_cannot_call_award_team_win(base_url, anon_key, non_editor_token):
    response = httpx.post(
        f"{base_url}/rest/v1/rpc/award_team_win",
        headers={
            "apikey": anon_key,
            "Authorization": f"Bearer {non_editor_token}",
            "Content-Type": "application/json",
        },
        json={},
        timeout=10,
    )
    assert response.status_code >= 400


def test_editor_can_insert_and_delete_a_point_event(base_url, anon_key, editor_token):
    players_response = httpx.get(
        f"{base_url}/rest/v1/players",
        headers={"apikey": anon_key, "Authorization": f"Bearer {editor_token}"},
        params={"select": "id", "limit": "1"},
        timeout=10,
    )
    players_response.raise_for_status()
    players = players_response.json()
    if not players:
        pytest.skip("Test project has no players to award a point to.")
    player_id = players[0]["id"]

    insert_response = httpx.post(
        f"{base_url}/rest/v1/point_events",
        headers={
            "apikey": anon_key,
            "Authorization": f"Bearer {editor_token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        json={"player_id": player_id, "category": "win"},
        timeout=10,
    )
    assert insert_response.status_code in (200, 201)
    event_id = insert_response.json()[0]["id"]

    delete_response = httpx.delete(
        f"{base_url}/rest/v1/point_events",
        headers={"apikey": anon_key, "Authorization": f"Bearer {editor_token}"},
        params={"id": f"eq.{event_id}"},
        timeout=10,
    )
    assert delete_response.status_code in (200, 204)
