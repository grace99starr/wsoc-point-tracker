"""Point operations and rankings.

This module computes derived data (totals, leaderboard order) and
validates inputs before handing off to database.py. database RLS is
still the real authorization boundary — nothing here enforces access.
"""
from __future__ import annotations

import streamlit as st

import database

VALID_CATEGORIES = {"win", "goal", "assist"}
_LEADERBOARD_VALUE_KEY = {
    "overall": "total",
    "win": "wins",
    "goal": "goals",
    "assist": "assists",
}


def _clean_name(name: str) -> str:
    return " ".join(name.strip().split())


@st.cache_data(ttl=30, show_spinner=False)
def get_player_totals(include_inactive: bool = False) -> list[dict]:
    rows = database.fetch_player_totals(include_inactive=include_inactive)
    totals = []
    for row in rows:
        wins, goals, assists = row["wins"], row["goals"], row["assists"]
        totals.append(
            {
                "id": row["player_id"],
                "name": row["name"],
                "active": row["active"],
                "wins": wins,
                "goals": goals,
                "assists": assists,
                "total": wins + goals + assists,
            }
        )
    return totals


@st.cache_data(ttl=15, show_spinner=False)
def get_recent_activity(limit: int = 20) -> list[dict]:
    return database.fetch_recent_activity(limit=limit)


def _clear_caches() -> None:
    get_player_totals.clear()
    get_recent_activity.clear()


def _competition_rank(sorted_items: list[dict], value_key: str) -> list[tuple[int, dict]]:
    """Standard competition ranking: ties share a rank, the next distinct
    value jumps to the count of players ranked so far plus one (1, 1, 3)."""
    ranked = []
    prev_value = None
    prev_rank = 0
    for idx, item in enumerate(sorted_items, start=1):
        value = item[value_key]
        if value != prev_value:
            prev_rank = idx
            prev_value = value
        ranked.append((prev_rank, item))
    return ranked


def get_leaderboard(category: str) -> list[dict]:
    category = category.lower()
    if category not in _LEADERBOARD_VALUE_KEY:
        raise ValueError(f"Unknown leaderboard category: {category}")
    value_key = _LEADERBOARD_VALUE_KEY[category]
    totals = get_player_totals(include_inactive=False)
    ordered = sorted(totals, key=lambda p: (-p[value_key], p["name"].casefold()))
    return [{"rank": rank, **player} for rank, player in _competition_rank(ordered, value_key)]


def add_player(name: str) -> str:
    cleaned = _clean_name(name)
    if not cleaned:
        raise ValueError("Player name cannot be empty.")
    try:
        return database.insert_player(cleaned)
    finally:
        _clear_caches()


def rename_player(player_id: str, new_name: str) -> None:
    cleaned = _clean_name(new_name)
    if not cleaned:
        raise ValueError("Player name cannot be empty.")
    try:
        database.update_player_name(player_id, cleaned)
    finally:
        _clear_caches()


def set_player_active(player_id: str, active: bool) -> None:
    try:
        database.update_player_active(player_id, active)
    finally:
        _clear_caches()


def award_point(player_id: str, category: str) -> str:
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Unknown point category: {category}")
    try:
        return database.insert_point_event(player_id, category)
    finally:
        _clear_caches()


def remove_latest_point(player_id: str, category: str) -> bool:
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Unknown point category: {category}")
    try:
        return database.delete_latest_point_event(player_id, category)
    finally:
        _clear_caches()


def delete_point_event(event_id: str) -> bool:
    try:
        return database.delete_point_event_by_id(event_id)
    finally:
        _clear_caches()


def award_team_win() -> int:
    try:
        return database.call_award_team_win()
    finally:
        _clear_caches()
