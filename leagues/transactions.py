"""Read-only transaction history from successful league sync observations."""

import json
from datetime import UTC, datetime

from players.models import Player
from roster_actions.models import AuditEvent

from .mcp_data import configured_league


def timestamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()
        except (ValueError, OverflowError, OSError):
            pass
    return None


def league_transactions_data(team_id=None, player_id=None, limit=50):
    if not 1 <= limit <= 200:
        raise ValueError("Limit must be between 1 and 200.")
    league = configured_league()
    events = AuditEvent.objects.filter(league=league, kind="espn.sync").order_by(
        "-created_at", "-pk"
    ) if league else AuditEvent.objects.none()
    teams = dict(league.teams.values_list("espn_id", "name")) if league else {}
    unique = {}
    latest_observed = None
    for event in events.iterator():
        latest_observed = latest_observed or event.created_at.isoformat()
        for raw in event.details.get("transactions", []):
            if not isinstance(raw, dict):
                continue
            key = str(raw["id"]) if raw.get("id") is not None else json.dumps(raw, sort_keys=True)
            if key not in unique:
                unique[key] = (raw, event)
    ids = {
        item.get("playerId") for raw, _ in unique.values()
        for item in (raw.get("items") or []) if isinstance(item, dict)
        and isinstance(item.get("playerId"), int)
    }
    names = dict(Player.objects.filter(espn_id__in=ids).values_list("espn_id", "name"))
    rows = []
    for raw, event in unique.values():
        items = []
        for item in raw.get("items") or []:
            if not isinstance(item, dict) or item.get("playerId") is None:
                continue
            action = item.get("type")
            if action not in {"ADD", "DROP", "TRADE"} and raw.get("type") != "TRADE_ACCEPT":
                continue
            from_id, to_id = item.get("fromTeamId"), item.get("toTeamId")
            items.append({
                "action": action,
                "player_id": item["playerId"],
                "player_name": names.get(item["playerId"], "Unknown player"),
                "from_team_id": from_id,
                "from_team": teams.get(from_id),
                "to_team_id": to_id,
                "to_team": teams.get(to_id),
            })
        if not items:
            continue
        if team_id is not None and not any(
            team_id in (item["from_team_id"], item["to_team_id"]) for item in items
        ):
            continue
        if player_id is not None and not any(item["player_id"] == player_id for item in items):
            continue
        rows.append({
            "transaction_id": str(raw["id"]) if raw.get("id") is not None else None,
            "type": raw.get("type"), "status": raw.get("status"),
            "processed_at": timestamp(raw.get("processDate")),
            "proposed_at": timestamp(raw.get("proposedDate")),
            "observed_at": event.created_at.isoformat(),
            "scoring_period": raw.get("scoringPeriodId", event.details.get("scoring_period")),
            "players": items,
        })
    rows.sort(key=lambda row: row["processed_at"] or row["proposed_at"] or row["observed_at"], reverse=True)
    return {
        "league": str(league) if league else None,
        "transactions": rows[:limit], "count": len(rows[:limit]),
        "total_matching": len(rows), "has_more": len(rows) > limit,
        "latest_observed_at": latest_observed,
        "coverage": "Saved ESPN sync observations only; not guaranteed complete season history. "
                    "Status is reported as supplied by ESPN; pending trade offers use list_trade_offers.",
    }
