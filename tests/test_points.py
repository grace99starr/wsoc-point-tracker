import points

SAMPLE_ROWS = [
    {"player_id": "1", "name": "Alex", "active": True, "wins": 2, "goals": 1, "assists": 0},
    {"player_id": "2", "name": "Bea", "active": True, "wins": 1, "goals": 1, "assists": 1},
    {"player_id": "3", "name": "Cy", "active": True, "wins": 1, "goals": 1, "assists": 1},
    {"player_id": "4", "name": "Dee", "active": True, "wins": 0, "goals": 0, "assists": 0},
]


def _patch_totals(monkeypatch, rows):
    points.get_player_totals.clear()
    monkeypatch.setattr(points.database, "fetch_player_totals", lambda include_inactive=False: rows)


def test_overall_total_equals_sum_of_categories(monkeypatch):
    _patch_totals(monkeypatch, SAMPLE_ROWS)
    for player in points.get_player_totals():
        assert player["total"] == player["wins"] + player["goals"] + player["assists"]


def test_leaderboard_overall_order_and_ties(monkeypatch):
    _patch_totals(monkeypatch, SAMPLE_ROWS)
    board = points.get_leaderboard("overall")
    assert [(p["name"], p["rank"]) for p in board] == [
        ("Alex", 1),
        ("Bea", 1),
        ("Cy", 1),
        ("Dee", 4),
    ]


def test_leaderboard_category_view_ranks_by_that_category(monkeypatch):
    _patch_totals(monkeypatch, SAMPLE_ROWS)
    board = points.get_leaderboard("win")
    assert [p["name"] for p in board] == ["Alex", "Bea", "Cy", "Dee"]
    assert [p["rank"] for p in board] == [1, 2, 2, 4]


def test_leaderboard_rejects_unknown_category(monkeypatch):
    _patch_totals(monkeypatch, SAMPLE_ROWS)
    try:
        points.get_leaderboard("not-a-category")
    except ValueError:
        return
    assert False, "expected ValueError for an unknown category"


def test_award_point_rejects_invalid_category():
    try:
        points.award_point("some-player-id", "red-card")
    except ValueError:
        return
    assert False, "expected ValueError for an invalid point category"


def test_remove_latest_point_rejects_invalid_category():
    try:
        points.remove_latest_point("some-player-id", "red-card")
    except ValueError:
        return
    assert False, "expected ValueError for an invalid point category"


def test_add_player_rejects_empty_name():
    try:
        points.add_player("   ")
    except ValueError:
        return
    assert False, "expected ValueError for an empty player name"


def test_set_point_count_rejects_invalid_category():
    try:
        points.set_point_count("some-player-id", "red-card", 3)
    except ValueError:
        return
    assert False, "expected ValueError for an invalid point category"


def test_set_point_count_rejects_negative_target():
    try:
        points.set_point_count("some-player-id", "win", -1)
    except ValueError:
        return
    assert False, "expected ValueError for a negative target count"


def test_set_point_count_inserts_difference_when_increasing(monkeypatch):
    calls = {}
    monkeypatch.setattr(points.database, "count_point_events", lambda player_id, category: 2)
    monkeypatch.setattr(
        points.database,
        "insert_point_events",
        lambda player_id, category, count: calls.update(inserted=count),
    )
    diff = points.set_point_count("player-1", "goal", 5)
    assert diff == 3
    assert calls["inserted"] == 3


def test_set_point_count_deletes_difference_when_decreasing(monkeypatch):
    calls = {}
    monkeypatch.setattr(points.database, "count_point_events", lambda player_id, category: 5)
    monkeypatch.setattr(
        points.database,
        "delete_latest_point_events",
        lambda player_id, category, count: calls.update(deleted=count),
    )
    diff = points.set_point_count("player-1", "goal", 2)
    assert diff == -3
    assert calls["deleted"] == 3
