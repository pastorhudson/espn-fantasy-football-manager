"""Bounded, model-readable trade evidence from saved ESPN observations."""

from django.conf import settings

from leagues.models import RosterSlot, TradeOffer
from players.models import Player


def offer_evidence(offer):
    league = offer.league
    teams = {team.espn_id: team for team in league.teams.all()}
    latest = {
        team.espn_id: team.roster_snapshots.order_by("-captured_at").first()
        for team in teams.values()
    }
    latest = {key: value for key, value in latest.items() if value}
    player_ids = {
        item.get("playerId") for item in offer.data.get("items", [])
        if isinstance(item, dict) and isinstance(item.get("playerId"), int)
    }
    players = {p.espn_id: p for p in Player.objects.filter(espn_id__in=player_ids)}
    slots = {
        (slot.snapshot.team.espn_id, slot.player.espn_id): slot
        for slot in RosterSlot.objects.filter(
            snapshot__in=latest.values(), player__espn_id__in=player_ids
        ).select_related("snapshot__team", "player")
    }
    items = []
    for raw in offer.data.get("items", []):
        if not isinstance(raw, dict):
            continue
        player = players.get(raw.get("playerId"))
        from_id, to_id = raw.get("fromTeamId"), raw.get("toTeamId")
        slot = slots.get((from_id, raw.get("playerId")))
        items.append({
            "player_id": raw.get("playerId"),
            "player_name": player.name if player else "Unknown player",
            "position_id": player.position_id if player else None,
            "injury_status": (slot.injury_status if slot else None)
            or (player.injury_status if player else None),
            "projected_points": slot.projected_points if slot else None,
            "from_team_id": from_id,
            "from_team": teams[from_id].name if from_id in teams else None,
            "to_team_id": to_id,
            "to_team": teams[to_id].name if to_id in teams else None,
            "transaction_type": raw.get("type"),
        })
    return {
        "offer_id": offer.espn_id, "status": offer.status, "active": offer.active,
        "league": str(league), "scoring_period": offer.scoring_period,
        "proposing_team": offer.proposing_team.name if offer.proposing_team else None,
        "manager_team": teams.get(settings.ESPN_TEAM_ID).name
        if settings.ESPN_TEAM_ID in teams else None,
        "process_at": offer.process_at.isoformat() if offer.process_at else None,
        "observed_at": offer.observed_at.isoformat(), "players": items,
        "analysis_notes": [
            "ESPN projections are estimates, not guarantees.",
            "Confirm offer status, roster limits, and trade deadline in ESPN.",
            "This application cannot accept, reject, or counter a trade.",
        ],
    }


def list_offer_evidence(*, active_only=True, limit=20):
    offers = TradeOffer.objects.select_related("league", "proposing_team")
    if active_only:
        offers = offers.filter(active=True)
    return [offer_evidence(offer) for offer in offers[:limit]]
