"""Fetch first, then persist one complete observation atomically."""

from datetime import UTC, datetime

from django.db import transaction
from django.utils import timezone

from decisions.models import ManagerPolicy
from leagues.models import (
    FantasyTeam,
    FreeAgentSnapshot,
    League,
    MatchupSnapshot,
    RosterSlot,
    RosterSnapshot,
    SyncLease,
    TradeOffer,
)
from players.models import Player
from roster_actions.models import AuditEvent

from .client import ESPNError


def points(player, season, week, source):
    for stat in player.get("stats", []):
        if (
            stat.get("seasonId") == season
            and stat.get("scoringPeriodId") == week
            and stat.get("statSourceId") == source
            and stat.get("statSplitTypeId") == 1
        ):
            return stat.get("appliedTotal")
    return None


def save_player(data):
    player, _ = Player.objects.update_or_create(
        espn_id=data["id"],
        defaults={
            "name": data["fullName"],
            "position_id": data["defaultPositionId"],
            "pro_team_id": data.get("proTeamId", 0),
            "eligible_slots": data.get("eligibleSlots", []),
            "injury_status": data.get("injuryStatus", ""),
        },
    )
    return player


def sync_league(client, *, team_id, week=None, free_agent_limit=100):
    from leagues.locking import sync_lease

    with sync_lease(client.league_id, client.season) as lease:
        return _fetch(
            client, team_id=team_id, week=week, free_agent_limit=free_agent_limit, lease=lease
        )


def _fetch(client, *, team_id, week, free_agent_limit, lease):
    data = client.league(week=week)
    try:
        period = week if week is not None else int(data["scoringPeriodId"])
        if period < 0:
            raise ValueError
        # Matchup periods can span multiple scoring periods (e.g. playoffs).
        matchup_period = data["status"]["currentMatchupPeriod"]
        if week is not None:
            periods = data["settings"].get("scheduleSettings", {}).get("matchupPeriods", {})
            matchup_period = next(
                (int(key) for key, weeks in periods.items() if period in weeks), None
            )
            if matchup_period is None:
                raise ESPNError(
                    "Requested week is not mapped to a matchup period in ESPN settings."
                )
        if not any(team["id"] == team_id for team in data["teams"]):
            raise ESPNError("ESPN_TEAM_ID is not in this league; no data was saved.")
        if not isinstance(data.get("schedule"), list):
            raise ESPNError("ESPN league response is missing the matchup schedule.")
        for team in data["teams"]:
            if not isinstance(team.get("roster", {}).get("entries"), list):
                raise ESPNError("ESPN team response is missing a roster; no data was saved.")
        free_agents = client.free_agents(week=period, limit=free_agent_limit)
        transactions = client.transactions(week=period)
        pending_transactions = client.pending_transactions(week=period)
        return _persist(
            client,
            data,
            period,
            matchup_period,
            team_id,
            free_agents,
            transactions,
            pending_transactions,
            free_agent_limit,
            lease,
        )
    except (KeyError, TypeError, ValueError, AttributeError, StopIteration):
        raise ESPNError(
            "ESPN returned incomplete or malformed league data; no data was saved."
        ) from None


@transaction.atomic
def _persist(
    client, data, period, matchup_period, team_id, free_agents, transactions,
    pending_transactions, limit, lease
):
    key, token = lease
    held = SyncLease.objects.select_for_update().get(key=key)
    if held.token != token or held.expires_at <= timezone.now():
        raise ESPNError("Sync lease expired; no data was saved.")
    league, _ = League.objects.update_or_create(
        espn_id=client.league_id,
        season=client.season,
        defaults={
            "name": data["settings"]["name"],
            "settings": data["settings"],
            "schedule": data["schedule"],
            "scoring_period": period,
            "matchup_period": matchup_period,
            "last_synced_at": timezone.now(),
        },
    )
    members = {
        member["id"]: {
            key: member[key]
            for key in ("id", "displayName", "firstName", "lastName")
            if key in member
        }
        for member in data.get("members", [])
    }
    selected = None
    for item in data["teams"]:
        team, _ = FantasyTeam.objects.update_or_create(
            league=league,
            espn_id=item["id"],
            defaults={
                "name": item.get("name")
                or " ".join(filter(None, [item.get("location"), item.get("nickname")]))
                or f"Team {item['id']}",
                "owners": [members.get(owner, {"id": owner}) for owner in item.get("owners", [])],
                "waiver_rank": item.get("waiverRank"),
                "transaction_counters": item.get("transactionCounter", {}),
            },
        )
        if team.espn_id == team_id:
            selected = team
            ManagerPolicy.objects.get_or_create(team=team)
        snapshot = RosterSnapshot.objects.create(team=team, scoring_period=period)
        for entry in item["roster"]["entries"]:
            player_data = entry["playerPoolEntry"]["player"]
            player = save_player(player_data)
            RosterSlot.objects.create(
                snapshot=snapshot,
                player=player,
                lineup_slot_id=entry["lineupSlotId"],
                projected_points=points(player_data, client.season, period, 1),
                actual_points=points(player_data, client.season, period, 0),
                injury_status=player.injury_status,
                eligible_slots=player.eligible_slots,
                pro_team_id=player.pro_team_id,
            )
    matchups = [item for item in data["schedule"] if item["matchupPeriodId"] == matchup_period]
    for item in matchups:
        MatchupSnapshot.objects.create(
            league=league,
            espn_id=item["id"],
            scoring_period=period,
            matchup_period=matchup_period,
            data=item,
        )
    for entry in free_agents:
        save_player(entry["player"])
    FreeAgentSnapshot.objects.create(
        league=league, scoring_period=period, limit=limit, data=free_agents
    )
    active_offer_ids = set()
    for offer in pending_transactions:
        offer_id = str(offer["id"])
        active_offer_ids.add(offer_id)
        process_ms = offer.get("processDate")
        process_at = (
            datetime.fromtimestamp(process_ms / 1000, tz=UTC)
            if isinstance(process_ms, (int, float)) and not isinstance(process_ms, bool)
            else None
        )
        TradeOffer.objects.update_or_create(
            league=league,
            espn_id=offer_id,
            defaults={
                "status": str(offer.get("status") or "PENDING"),
                "proposing_team": FantasyTeam.objects.filter(
                    league=league, espn_id=offer.get("teamId")
                ).first(),
                "scoring_period": period,
                "process_at": process_at,
                "active": True,
                "data": offer,
            },
        )
    TradeOffer.objects.filter(league=league, active=True).exclude(
        espn_id__in=active_offer_ids
    ).update(active=False)
    AuditEvent.objects.create(
        league=league,
        kind="espn.sync",
        details={
            "scoring_period": period,
            "team_count": len(data["teams"]),
            "free_agent_count": len(free_agents),
            "transactions": transactions,
            "pending_trade_count": len(pending_transactions),
        },
    )
    return league, selected, matchups
