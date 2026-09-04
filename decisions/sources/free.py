"""Schedule safety and supplemental Sleeper context, saved with each decision."""

from datetime import UTC, datetime

from django.utils import timezone

from leagues.models import FreeAgentSnapshot

from .client import SourceError, cached_feed

SLEEPER_DOCS = "https://docs.sleeper.com/"
SCHEDULE_BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/"


def parse_schedule(data):
    teams = data["settings"]["proTeams"]
    if not isinstance(teams, list) or not teams:
        raise ValueError
    result = {}
    for team in teams:
        tid = str(int(team["id"]))
        if tid in result:
            raise ValueError
        result[tid] = {
            "name": str(team.get("abbrev", tid)),
            "bye_week": team.get("byeWeek"),
            "games": team.get("proGamesByScoringPeriod", {}),
        }
        if not isinstance(result[tid]["games"], dict):
            raise ValueError
    return result


def reported_status(value):
    """Treat provider placeholders as absent, including values in existing caches."""
    if isinstance(value, str) and value.strip().upper() in {"", "NA", "N/A"}:
        return None
    return value


def parse_players(data):
    if not isinstance(data, dict) or not data:
        raise ValueError
    result = {}
    for sid, player in data.items():
        if not isinstance(player, dict):
            raise ValueError
        espn = player.get("espn_id")
        if espn is None or str(espn) == "0":
            continue
        result[str(sid)] = {
            "espn_id": int(espn),
            "name": player.get("full_name") or " ".join(
                str(player.get(key) or "") for key in ("first_name", "last_name")
            ).strip(),
            "injury_status": player.get("injury_status"),
            "practice": player.get("practice_participation"),
        }
    return result


def parse_trends(data):
    if not isinstance(data, list):
        raise ValueError
    result = []
    for row in data[:25]:
        count = row["count"]
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError
        result.append({"sleeper_id": str(row["player_id"]), "count": count})
    return result


def game_context(team, week, now):
    """Never infer a bye from an absent game; never equate kickoff with ESPN locks."""
    unknown = {"state": "unknown", "kickoff": None, "game_id": None}
    if not team:
        return unknown
    games = team["games"].get(str(week), [])
    if team["bye_week"] == week:
        return unknown if games else {**unknown, "state": "bye"}
    if not isinstance(games, list) or len(games) != 1:
        return unknown
    game = games[0]
    if not isinstance(game, dict):
        return unknown
    if game.get("startTimeTBD") is not False or game.get("validForLocking") is not True:
        return unknown
    try:
        stamp = game["date"]
        if not isinstance(stamp, (int, float)) or isinstance(stamp, bool):
            return unknown
        kickoff = datetime.fromtimestamp(stamp / 1000, tz=UTC)
    except (KeyError, ValueError, OverflowError, OSError):
        return unknown
    return {
        "state": "started" if kickoff <= now else "scheduled",
        "kickoff": kickoff.isoformat(), "game_id": game.get("id"),
    }


def collect_context(snapshot):
    """HTTP runs before decision persistence; only bounded evidence is retained."""
    now = timezone.now()
    rows = list(snapshot.slots.select_related("player").order_by("player__espn_id"))
    league = snapshot.team.league
    evidence = {
        "version": "free-sources-v2", "evaluated_at": now.isoformat(),
        "sources": [], "players": [], "waiver_trends": [], "warnings": [],
    }
    schedule_url = f"{SCHEDULE_BASE}{league.season}?view=proTeamSchedules_wl"
    schedule = {}
    try:
        schedule, fetched = cached_feed(
            f"espn-schedule-{league.season}", schedule_url, 15, parse_schedule
        )
        evidence["sources"].append({
            "name": "ESPN NFL schedule", "url": schedule_url, "status": "available",
            "fetched_at": fetched.isoformat(), "updated_at": "Not supplied",
        })
    except SourceError as exc:
        evidence["sources"].append({
            "name": "ESPN NFL schedule", "url": schedule_url, "status": "unavailable",
            "error": str(exc),
        })
        evidence["warnings"].append("NFL schedule unavailable; lineup evaluation is blocked.")

    players = {}
    try:
        players, fetched = cached_feed(
            "sleeper-players", "https://api.sleeper.app/v1/players/nfl", 1440, parse_players
        )
        evidence["sources"].append({
            "name": "Sleeper players", "url": SLEEPER_DOCS, "status": "available",
            "fetched_at": fetched.isoformat(), "updated_at": "Not supplied",
        })
    except SourceError as exc:
        evidence["sources"].append({
            "name": "Sleeper players", "url": SLEEPER_DOCS,
            "status": "unavailable", "error": str(exc),
        })
        evidence["warnings"].append("Sleeper player context unavailable; ESPN projections retained.")
    # Duplicate cross-references are ambiguous. Never guess by player name.
    by_espn = {}
    for sid, player in players.items():
        by_espn.setdefault(player["espn_id"], []).append({**player, "sleeper_id": sid})
    for row in rows:
        matches = by_espn.get(row.player.espn_id, [])
        secondary = matches[0] if len(matches) == 1 else {}
        if row.player.espn_id < 0:
            mapping = "not applicable"
            mapping_note = "Team defense; no individual injury report"
        elif len(matches) > 1:
            mapping = "ambiguous"
            mapping_note = "Multiple Sleeper players share this ESPN ID"
        elif not players:
            mapping = "unavailable"
            mapping_note = "Sleeper player feed unavailable"
        elif not matches:
            mapping = "unmapped"
            mapping_note = "No matching ESPN ID in Sleeper data"
        else:
            mapping = "matched"
            mapping_note = "Matched by ESPN ID"
        team = schedule.get(str(row.pro_team_id))
        item = {
            "player_id": row.player.espn_id, "name": row.player.name,
            "pro_team_id": row.pro_team_id, "espn_injury": row.injury_status,
            **game_context(team, snapshot.scoring_period, now),
            "sleeper_id": secondary.get("sleeper_id"),
            "sleeper_injury": reported_status(secondary.get("injury_status")),
            "practice": reported_status(secondary.get("practice")),
            "mapping": mapping, "mapping_note": mapping_note,
        }
        evidence["players"].append(item)
        if item["sleeper_injury"]:
            evidence["warnings"].append(
                f"{row.player.name}: Sleeper reports {item['sleeper_injury']} "
                "(supplemental context; source update time unknown)."
            )

    try:
        trends, fetched = cached_feed(
            "sleeper-trending-adds",
            "https://api.sleeper.app/v1/players/nfl/trending/add?lookback_hours=24&limit=25",
            60, parse_trends,
        )
        evidence["sources"].append({
            "name": "Sleeper trending adds (24 hours)", "url": SLEEPER_DOCS,
            "status": "available", "fetched_at": fetched.isoformat(),
            "updated_at": "Not supplied",
        })
        pool = FreeAgentSnapshot.objects.filter(
            league=league, scoring_period=snapshot.scoring_period,
            captured_at__gte=snapshot.captured_at,
        ).order_by("-captured_at").first()
        # A bounded observation is evidence of presence, never proof of absence.
        available = {}
        if pool:
            evidence["free_agent_sample"] = {
                "id": pool.pk, "captured_at": pool.captured_at.isoformat(), "limit": pool.limit,
            }
            for entry in pool.data:
                if entry.get("status") in ("FREEAGENT", "WAIVERS"):
                    available[entry["player"]["id"]] = entry
        roster_ids = {row.player.espn_id for row in rows}
        for trend in trends:
            player = players.get(trend["sleeper_id"])
            if not player or len(by_espn.get(player["espn_id"], [])) != 1:
                continue
            entry = available.get(player["espn_id"])
            if entry and player["espn_id"] not in roster_ids:
                evidence["waiver_trends"].append({
                    "player_id": player["espn_id"], "name": entry["player"]["fullName"],
                    "adds": trend["count"], "status": entry["status"],
                })
    except SourceError as exc:
        evidence["sources"].append({
            "name": "Sleeper trending adds (24 hours)", "url": SLEEPER_DOCS,
            "status": "unavailable", "error": str(exc),
        })
    return evidence
