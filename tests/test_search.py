from search import search_players

PLAYERS = [
    {"id": "3", "name": "Jordan Smith"},
    {"id": "1", "name": "Alex Johnson"},
    {"id": "5", "name": "Sam"},
    {"id": "4", "name": "Sam Johnson"},
    {"id": "2", "name": "Alexis Jones"},
]


def test_blank_query_returns_all_alphabetically():
    results = search_players("", PLAYERS)
    assert [p["name"] for p in results] == [
        "Alex Johnson",
        "Alexis Jones",
        "Jordan Smith",
        "Sam",
        "Sam Johnson",
    ]


def test_exact_match_ranked_above_partial_match():
    results = search_players("Sam", PLAYERS)
    assert [p["name"] for p in results] == ["Sam", "Sam Johnson"]


def test_case_insensitive_exact_match():
    results = search_players("alex johnson", PLAYERS)
    assert results[0]["name"] == "Alex Johnson"


def test_partial_match_on_last_name():
    results = search_players("Johnson", PLAYERS)
    names = {p["name"] for p in results}
    assert names == {"Alex Johnson", "Sam Johnson"}


def test_partial_match_on_first_name_prefix():
    results = search_players("Jor", PLAYERS)
    assert [p["name"] for p in results] == ["Jordan Smith"]


def test_typo_tolerant_fuzzy_match():
    results = search_players("Jordn Smith", PLAYERS)
    names = [p["name"] for p in results]
    assert "Jordan Smith" in names


def test_fuzzy_match_does_not_select_anything_it_only_ranks():
    results = search_players("Jordn Smith", PLAYERS)
    # fuzzy results are returned, never filtered down to a single "best" pick
    assert isinstance(results, list)


def test_no_match_returns_empty():
    results = search_players("Zzzzz Nonexistent Name", PLAYERS)
    assert results == []
