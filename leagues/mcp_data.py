"""Read-only league and projection data shaped for MCP tool results."""

from django.conf import settings

from decisions.views import slot_name
from leagues.espn.sync import points
from leagues.models import FreeAgentSnapshot, League


def configured_league():
    return League.objects.filter(
        espn_id=settings.ESPN_LEAGUE_ID, season=settings.ESPN_SEASON
    ).first()


def player_row(slot):
    return {
        "player_id": slot.player.espn_id,
        "name": slot.player.name,
        "position_id": slot.player.position_id,
        "lineup_slot_id": slot.lineup_slot_id,
        "lineup_slot": slot_name(slot.lineup_slot_id),
        "projected_points": slot.projected_points,
        "actual_points": slot.actual_points,
        "injury_status": slot.injury_status or None,
        "eligible_slot_ids": slot.eligible_slots,
        "pro_team_id": slot.pro_team_id,
    }


def latest_rosters():
    league = configured_league()
    if not league:
        return None, []
    rosters = []
    for team in league.teams.order_by("espn_id"):
        snapshot = team.roster_snapshots.order_by("-captured_at").first()
        if not snapshot:
            continue
        slots = snapshot.slots.select_related("player").order_by("lineup_slot_id", "player__name")
        rosters.append({
            "team_id": team.espn_id,
            "team_name": team.name,
            "is_manager_team": team.espn_id == settings.ESPN_TEAM_ID,
            "waiver_rank": team.waiver_rank,
            "scoring_period": snapshot.scoring_period,
            "captured_at": snapshot.captured_at.isoformat(),
            "players": [player_row(slot) for slot in slots],
        })
    return league, rosters


def league_teams_data():
    league, rosters = latest_rosters()
    if not league:
        return {"league": None, "teams": [], "count": 0}
    teams = [{key: roster[key] for key in (
        "team_id", "team_name", "is_manager_team", "waiver_rank", "captured_at"
    )} | {"roster_size": len(roster["players"])} for roster in rosters]
    return {"league": str(league), "scoring_period": league.scoring_period,
            "teams": teams, "count": len(teams)}


def league_rosters_data():
    league, rosters = latest_rosters()
    return {"league": str(league) if league else None, "rosters": rosters,
            "count": len(rosters)}


def manager_roster_data():
    league, rosters = latest_rosters()
    roster = next((row for row in rosters if row["is_manager_team"]), None)
    return {"league": str(league) if league else None, "roster": roster,
            "found": roster is not None}


def player_projections_data():
    league, rosters = latest_rosters()
    if not league:
        return {"league": None, "players": [], "coverage": {}}
    projected = {}
    for roster in rosters:
        for player in roster["players"]:
            projected[player["player_id"]] = {
                **player,
                "fantasy_status": "ROSTERED",
                "fantasy_team_id": roster["team_id"],
                "fantasy_team": roster["team_name"],
                "source_observed_at": roster["captured_at"],
            }
    sample = FreeAgentSnapshot.objects.filter(
        league=league, scoring_period=league.scoring_period
    ).order_by("-captured_at").first()
    if sample:
        for entry in sample.data:
            raw = entry.get("player", {})
            player_id = raw.get("id")
            if not isinstance(player_id, int) or player_id in projected:
                continue
            projected[player_id] = {
                "player_id": player_id,
                "name": raw.get("fullName") or "Unknown player",
                "position_id": raw.get("defaultPositionId"),
                "projected_points": points(
                    raw, league.season, league.scoring_period, 1
                ),
                "injury_status": raw.get("injuryStatus") or None,
                "eligible_slot_ids": raw.get("eligibleSlots", []),
                "pro_team_id": raw.get("proTeamId"),
                "fantasy_status": entry.get("status"),
                "fantasy_team_id": None,
                "fantasy_team": None,
                "source_observed_at": sample.captured_at.isoformat(),
            }
    players = sorted(projected.values(), key=lambda row: (row["name"], row["player_id"]))
    return {
        "league": str(league), "scoring_period": league.scoring_period,
        "players": players,
        "coverage": {
            "total": len(players),
            "with_projection": sum(row["projected_points"] is not None for row in players),
            "rostered": sum(row["fantasy_status"] == "ROSTERED" for row in players),
            "free_agent_sample_limit": sample.limit if sample else 0,
            "is_full_espn_player_universe": False,
        },
    }
