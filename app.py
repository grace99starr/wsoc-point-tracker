"""Soccer Team Points Tracker — Streamlit UI, role-aware rendering.

Every control in this file is just a show/hide convenience. The actual
authorization boundary is Supabase RLS (see sql/schema.sql) — a hidden
button is not security, and every mutation below would still be
rejected by the database if the caller weren't an allowlisted editor.
"""
from __future__ import annotations

import auth
import database
import points
import streamlit as st
from database import DatabaseError
from search import search_players

SEASON_SUBTITLE = "2026 Season"

CATEGORY_LABELS = (("win", "Win", "wins"), ("goal", "Goal", "goals"), ("assist", "Assist", "assists"))
LEADERBOARD_VIEWS = (("overall", "Overall"), ("win", "Wins"), ("goal", "Goals"), ("assist", "Assists"))
_LEADERBOARD_FIELD = {"win": "wins", "goal": "goals", "assist": "assists"}
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

st.set_page_config(page_title="Team Points Tracker", page_icon="⚽", layout="centered")


def _flash(kind: str, message: str) -> None:
    st.session_state["_flash"] = (kind, message)


def _render_flash() -> None:
    flash = st.session_state.pop("_flash", None)
    if flash:
        kind, message = flash
        getattr(st, kind)(message)


def _run_mutation(action, *args, success_message: str | None = None, **kwargs):
    """Run a points.* mutation; turn errors into a flash message instead of
    a crash, and always rerun afterward so totals refresh immediately for
    the person who just acted."""
    try:
        result = action(*args, **kwargs)
    except ValueError as exc:
        _flash("warning", str(exc))
        st.rerun()
        return None
    except DatabaseError as exc:
        _flash("error", str(exc))
        if database.is_auth_error(exc):
            auth.sign_out()
        st.rerun()
        return None

    if success_message:
        _flash("success", success_message)
    st.rerun()
    return result


def render_sidebar() -> None:
    with st.sidebar:
        st.subheader("Editor")
        if auth.is_signed_in():
            email = auth.current_user_email()
            if auth.is_approved_editor():
                st.success(f"Signed in as {email}")
            else:
                st.info(
                    f"Signed in as {email}, but this account isn't an "
                    "approved editor yet. You can view everything; ask the "
                    "team owner to add you to the allowlist to edit."
                )
            if st.button("Log out"):
                auth.sign_out()
                st.rerun()
        else:
            st.caption("Editor login")
            with st.form("editor_login"):
                email = st.text_input("Email")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Sign in")
            if submitted:
                ok, message = auth.sign_in(email, password)
                if ok:
                    st.rerun()
                else:
                    st.error(message)


def render_player_card(player: dict, is_editor: bool) -> None:
    with st.container(border=True):
        name_col, total_col = st.columns([3, 1])
        name_col.markdown(f"**{player['name']}**")
        total_col.markdown(f"**{player['total']} pts**")

        cols = st.columns(3)
        for col, (category, label, field) in zip(cols, CATEGORY_LABELS):
            with col:
                st.caption(label)
                st.markdown(f"#### {player[field]}")
                if is_editor:
                    plus_col, minus_col = st.columns(2)
                    if plus_col.button("➕", key=f"plus_{player['id']}_{category}", use_container_width=True):
                        _run_mutation(
                            points.award_point,
                            player["id"],
                            category,
                            success_message=f"{label} added for {player['name']}.",
                        )
                    if minus_col.button(
                        "➖",
                        key=f"minus_{player['id']}_{category}",
                        use_container_width=True,
                        disabled=player[field] == 0,
                    ):
                        _run_mutation(
                            points.remove_latest_point,
                            player["id"],
                            category,
                            success_message=f"Last {label.lower()} undone for {player['name']}.",
                        )


def render_players_tab(is_editor: bool) -> None:
    query = st.text_input(
        "Search", key="player_search", placeholder="Search player name...", label_visibility="collapsed"
    )
    totals = points.get_player_totals()

    if not totals:
        st.info("No active players yet." + (" Add one from Manage Team." if is_editor else ""))
        return

    results = search_players(query, totals)
    if not results:
        st.info(f'No players found matching "{query}".')
    else:
        for player in results:
            render_player_card(player, is_editor)

    if not is_editor:
        st.caption("Scores update automatically every 30s, or:")
        if st.button("🔄 Refresh"):
            points.get_player_totals.clear()
            st.rerun()


def render_leaderboard_tab() -> None:
    labels = [label for _, label in LEADERBOARD_VIEWS]
    choice = st.radio("View", labels, horizontal=True, key="leaderboard_view", label_visibility="collapsed")
    category = next(key for key, label in LEADERBOARD_VIEWS if label == choice)
    rows = points.get_leaderboard(category)

    if not rows:
        st.info("No active players yet.")
        return

    def _rank_label(rank: int) -> str:
        medal = MEDALS.get(rank, "")
        return f"{medal} {rank}".strip()

    if category == "overall":
        table = [
            {
                "Rank": _rank_label(r["rank"]),
                "Player": r["name"],
                "Wins": r["wins"],
                "Goals": r["goals"],
                "Assists": r["assists"],
                "Total": r["total"],
            }
            for r in rows
        ]
    else:
        value_key = _LEADERBOARD_FIELD[category]
        column_label = choice
        table = [
            {"Rank": _rank_label(r["rank"]), "Player": r["name"], column_label: r[value_key]}
            for r in rows
        ]

    st.dataframe(table, hide_index=True, use_container_width=True)


def render_manage_tab() -> None:
    st.subheader("Add player")
    with st.form("add_player_form", clear_on_submit=True):
        new_name = st.text_input("Player name")
        add_submitted = st.form_submit_button("Add player")
    if add_submitted:
        _run_mutation(points.add_player, new_name, success_message=f'Added "{_safe(new_name)}".')

    st.divider()
    st.subheader("Award win to entire team")
    active_totals = points.get_player_totals()
    active_count = len(active_totals)
    st.write(f"{active_count} active player(s) will each receive one win point.")
    confirm = st.checkbox("I understand this applies to every active player at once", key="confirm_team_win")
    if st.button("🏆 Award Win to Entire Team", disabled=not confirm or active_count == 0):
        _run_mutation(points.award_team_win, success_message=f"Awarded a win to {active_count} player(s).")

    st.divider()
    st.subheader("Roster")
    if not active_totals:
        st.caption("No active players yet.")
    for player in active_totals:
        with st.container(border=True):
            cols = st.columns([3, 3, 2, 2])
            cols[0].markdown(f"**{player['name']}**")
            rename_value = cols[1].text_input(
                "Rename", value=player["name"], key=f"rename_{player['id']}", label_visibility="collapsed"
            )
            if cols[2].button("Save", key=f"save_{player['id']}"):
                if rename_value.strip() and rename_value.strip() != player["name"]:
                    _run_mutation(
                        points.rename_player,
                        player["id"],
                        rename_value,
                        success_message=f'Renamed to "{_safe(rename_value)}".',
                    )
            if cols[3].button("Deactivate", key=f"deactivate_{player['id']}"):
                _run_mutation(
                    points.set_player_active,
                    player["id"],
                    False,
                    success_message=f"{player['name']} deactivated.",
                )

    st.divider()
    st.subheader("Inactive players")
    inactive = [p for p in points.get_player_totals(include_inactive=True) if not p["active"]]
    if not inactive:
        st.caption("No inactive players.")
    for player in inactive:
        cols = st.columns([4, 2])
        cols[0].write(f"{player['name']} — {player['total']} pts (history preserved)")
        if cols[1].button("Reactivate", key=f"reactivate_{player['id']}"):
            _run_mutation(
                points.set_player_active,
                player["id"],
                True,
                success_message=f"{player['name']} reactivated.",
            )

    st.divider()
    st.subheader("Recent activity")
    activity = points.get_recent_activity(limit=20)
    if not activity:
        st.caption("No activity yet.")
    for event in activity:
        cols = st.columns([4, 1])
        cols[0].write(f"**{event['player_name']}** — {event['category']} — {event['created_at']}")
        if cols[1].button("Undo", key=f"undo_event_{event['id']}"):
            _run_mutation(points.delete_point_event, event["id"], success_message="Point removed.")


def _safe(name: str) -> str:
    return name.strip()


def main() -> None:
    _render_flash()

    st.title("⚽ Team Points Tracker")
    st.caption(SEASON_SUBTITLE)

    render_sidebar()
    is_editor = auth.is_approved_editor()

    totals = points.get_player_totals()
    total_points = sum(p["total"] for p in totals)
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Points", total_points)
    m2.metric("Team Players", len(totals))
    m3.metric("Categories", 3)

    tab_labels = ["Players", "Leaderboard"] + (["Manage Team"] if is_editor else [])
    tabs = st.tabs(tab_labels)

    with tabs[0]:
        render_players_tab(is_editor)
    with tabs[1]:
        render_leaderboard_tab()
    if is_editor:
        with tabs[2]:
            render_manage_tab()


if __name__ == "__main__":
    try:
        main()
    except DatabaseError as exc:
        st.error(str(exc))
