"""Exact, partial, and fuzzy player-name search. Pure logic, no database access."""
from __future__ import annotations

from difflib import SequenceMatcher

_FUZZY_THRESHOLD = 0.72


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def _name_parts(name: str) -> list[str]:
    return _normalize(name).split(" ")


def search_players(query: str, players: list[dict]) -> list[dict]:
    """Rank `players` (each needs a 'name' key) against `query`.

    Tiers, in order: exact full-name match, then substring match (anywhere
    in the full name, or a prefix of any individual name part — covers
    first/last name search), then conservative fuzzy matches. Each tier is
    sorted alphabetically within itself. A blank query returns everyone,
    alphabetically.
    """
    normalized_query = _normalize(query)
    if not normalized_query:
        return sorted(players, key=lambda p: p["name"].casefold())

    exact, partial, fuzzy = [], [], []
    for player in players:
        normalized_name = _normalize(player["name"])
        if normalized_name == normalized_query:
            exact.append(player)
            continue

        parts = _name_parts(player["name"])
        if normalized_query in normalized_name or any(
            part.startswith(normalized_query) for part in parts
        ):
            partial.append(player)
            continue

        ratio = max(
            SequenceMatcher(None, normalized_query, normalized_name).ratio(),
            max(
                (SequenceMatcher(None, normalized_query, part).ratio() for part in parts),
                default=0.0,
            ),
        )
        if ratio >= _FUZZY_THRESHOLD:
            fuzzy.append(player)

    def _alpha(group: list[dict]) -> list[dict]:
        return sorted(group, key=lambda p: p["name"].casefold())

    return _alpha(exact) + _alpha(partial) + _alpha(fuzzy)
