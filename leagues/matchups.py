"""Shared, read-only matchup evidence for the web view and MCP."""

from django.conf import settings

from .mcp_data import configured_league, player_row


def schedule_data(team_id=None):
    league = configured_league()
    if not league:
        return {"league": None, "matchups": [], "count": 0, "full_schedule_saved": False}
    names = dict(league.teams.values_list("espn_id", "name"))
    raw = league.schedule
    observed = league.last_synced_at
    if raw is None:
        # Existing installations can expose current saved evidence before their next sync.
        latest = {}
        for snapshot in league.matchup_snapshots.order_by("-captured_at", "-pk"):
            latest.setdefault(snapshot.espn_id, snapshot.data)
        raw = list(latest.values())
    periods = league.settings.get("scheduleSettings", {}).get("matchupPeriods", {})

    def side(value):
        value = value or {}
        ident = value.get("teamId")
        return {
            "team_id": ident, "team_name": names.get(ident, f"Team {ident}" if ident else None),
            "is_manager_team": ident == settings.ESPN_TEAM_ID,
            "total_points": value.get("totalPoints"),
        }

    rows = []
    for item in raw:
        home, away = side(item.get("home")), side(item.get("away"))
        if team_id is not None and team_id not in (home["team_id"], away["team_id"]):
            continue
        rows.append({
            "matchup_id": item["id"], "matchup_period": item["matchupPeriodId"],
            "scoring_periods": periods.get(str(item["matchupPeriodId"]), []),
            "home": home, "away": away,
            "has_open_side": home["team_id"] is None or away["team_id"] is None,
            "winner": item.get("winner"),
        })
    rows.sort(key=lambda row: (row["matchup_period"], row["matchup_id"]))
    return {
        "league": str(league), "scoring_period": league.scoring_period,
        "matchup_period": league.matchup_period,
        "observed_at": observed.isoformat() if observed else None,
        "full_schedule_saved": league.schedule is not None,
        "matchups": rows, "count": len(rows),
    }


def matchups_data(week=None, team_id=None):
    league = configured_league()
    result = schedule_data(team_id)
    if not league:
        return result
    week = league.scoring_period if week is None else week
    periods = league.settings.get("scheduleSettings", {}).get("matchupPeriods", {})
    period = next((int(key) for key, weeks in periods.items() if week in weeks), None)
    if period is None and week == league.scoring_period:
        period = league.matchup_period
    result["scoring_period"] = week
    result["matchup_period"] = period
    result["matchups"] = [row for row in result["matchups"] if row["matchup_period"] == period]
    for row in result["matchups"]:
        for key in ("home", "away"):
            side = row[key]
            snapshot = league.teams.filter(espn_id=side["team_id"]).first()
            snapshot = snapshot.roster_snapshots.filter(scoring_period=week).order_by(
                "-captured_at", "-pk"
            ).first() if snapshot else None
            starters = [
                player_row(slot) for slot in snapshot.slots.select_related("player").order_by(
                    "lineup_slot_id", "player__name"
                ) if slot.lineup_slot_id not in (20, 21)
            ] if snapshot else []
            side.update({
                "lineup_available": snapshot is not None,
                "lineup_observed_at": snapshot.captured_at.isoformat() if snapshot else None,
                "starters": starters,
                "projected_starter_total": (
                    sum(p["projected_points"] for p in starters)
                    if starters and all(p["projected_points"] is not None for p in starters)
                    else None
                ),
            })
    result["count"] = len(result["matchups"])
    return result


def my_matchup_data(week=None):
    return matchups_data(week=week, team_id=settings.ESPN_TEAM_ID)
