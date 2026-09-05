"""Live public ESPN NFL schedules joined to saved fantasy roster evidence."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from django.conf import settings
from django.utils import timezone

from .mcp_data import configured_league, player_row

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"


def nfl_schedule_data(week=None, timezone_name="America/New_York"):
    league = configured_league()
    week = week if week is not None else (league.scoring_period if league else None)
    if week is None or not 1 <= week <= 18:
        raise ValueError("Specify an NFL regular-season week from 1 to 18.")
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        raise ValueError("Use an IANA time zone such as America/New_York.") from None
    season = league.season if league else settings.ESPN_SEASON
    result = {
        "season": season, "week": week, "season_type": "regular",
        "timezone": timezone_name, "source": SCOREBOARD_URL,
        "observed_at": timezone.now().isoformat(), "available": False, "games": [],
    }
    try:
        response = httpx.get(SCOREBOARD_URL, params={
            "dates": season, "seasontype": 2, "week": week, "limit": 100,
        }, timeout=15)
        response.raise_for_status()
        data = response.json()
        if (data.get("season", {}).get("year") != season
                or data.get("season", {}).get("type") != 2
                or data.get("week", {}).get("number") != week
                or not isinstance(data.get("events"), list)):
            raise ValueError("Unexpected ESPN week")
        games = []
        for event in data["events"]:
            competition = event["competitions"][0]
            status = competition.get("status", event.get("status", {})).get("type", {})
            kickoff = datetime.fromisoformat(competition["date"].replace("Z", "+00:00"))
            time_confirmed = competition.get("timeValid") is True
            games.append({
                "game_id": event["id"], "name": event["name"],
                "kickoff": kickoff.astimezone(zone).isoformat() if time_confirmed else None,
                "time_confirmed": time_confirmed,
                "status": status.get("name"), "state": status.get("state"),
                "status_detail": status.get("detail"),
                "teams": [{"pro_team_id": int(c["team"]["id"]),
                           "name": c["team"]["displayName"], "home_away": c["homeAway"]}
                          for c in competition["competitors"]],
            })
        result.update(available=True, games=sorted(games, key=lambda g: g["kickoff"] or "9999"))
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
        result["error"] = "ESPN schedule unavailable or unexpected; kickoff times are unknown."
    return result


def player_schedule_data(week=None, team_id=None, player_id=None,
                         timezone_name="America/New_York"):
    league = configured_league()
    if not league:
        return {"league": None, "players": [], "available": False}
    result = nfl_schedule_data(week, timezone_name)
    team_id = settings.ESPN_TEAM_ID if team_id is None else team_id
    team = league.teams.filter(espn_id=team_id).first()
    # Use the most recently observed roster; explicitly label its scoring period.
    snapshot = team.roster_snapshots.order_by("-captured_at", "-pk").first() if team else None
    rows = []
    now = timezone.now()
    for slot in snapshot.slots.select_related("player").order_by("player__name") if snapshot else []:
        if player_id is not None and slot.player.espn_id != player_id:
            continue
        games = [g for g in result["games"] if any(
            t["pro_team_id"] == slot.pro_team_id for t in g["teams"]
        )]
        row = player_row(slot)
        row.update(is_starter=slot.lineup_slot_id not in (20, 21), games=games,
                   schedule_status="scheduled" if games else "no_game_found" if result["available"]
                   else "unknown", suggested_review_at=None, kickoff_has_passed=None)
        if games and games[0]["kickoff"]:
            kickoff = datetime.fromisoformat(games[0]["kickoff"])
            row["kickoff_has_passed"] = kickoff <= now
            if games[0]["status"] == "STATUS_SCHEDULED":
                row["suggested_review_at"] = (kickoff - timedelta(minutes=90)).isoformat()
        rows.append(row)
    kickoffs = [g["kickoff"] for p in rows for g in p["games"] if g["kickoff"]]
    upcoming = [g["kickoff"] for p in rows for g in p["games"] if g["kickoff"]
                and datetime.fromisoformat(g["kickoff"]) > now
                and g["status"] == "STATUS_SCHEDULED"]
    result.update(
        league=str(league), team_id=team_id, team_name=team.name if team else None,
        roster_available=snapshot is not None,
        roster_observed_at=snapshot.captured_at.isoformat() if snapshot else None,
        roster_scoring_period=snapshot.scoring_period if snapshot else None,
        players=rows, first_kickoff=min(kickoffs, default=None),
        next_kickoff=min(upcoming, default=None),
        lineup_lock_settings=league.settings.get("rosterSettings", {}),
        guidance=[
            "Kickoff times are live ESPN data; roster, projections, and injury status are saved observations.",
            "Review time is a suggested 90-minute planning buffer, not confirmed inactive news or a lineup lock.",
            "Confirm eligibility, injury news, and league lock rules in ESPN before kickoff. "
            "When choosing between players, decide before the earlier player's game; bench alternatives can lock too.",
            "No game found may mean a bye, missing team mapping, or incomplete schedule; it does not confirm a bye.",
            "First kickoff includes all returned players, including bench/IR; next kickoff excludes past games. "
            "Player filtering narrows both summaries. Future weeks use the latest saved roster.",
        ],
    )
    return result
