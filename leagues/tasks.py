"""Scheduled read-only observation and shadow evaluation."""

from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from decisions.lineup import recommend_lineup
from leagues.espn.client import ESPNClient, ESPNError
from leagues.espn.sync import sync_league
from leagues.models import FreeAgentSnapshot, MatchupSnapshot, RosterSnapshot
from roster_actions.models import AuditEvent


@transaction.atomic
def prune_snapshots(league, days=30):
    if days < 1:
        raise ValueError("Retention must be at least one day.")
    cutoff = timezone.now() - timedelta(days=days)
    # Keep latest observations per team and all evidence referenced by a decision.
    latest = [
        team.roster_snapshots.values_list("pk", flat=True).first() for team in league.teams.all()
    ]
    RosterSnapshot.objects.filter(
        team__league=league, captured_at__lt=cutoff, decision__isnull=True
    ).exclude(pk__in=latest).delete()
    latest_free_agents = (
        FreeAgentSnapshot.objects.filter(league=league).order_by("-captured_at").first()
    )
    if latest_free_agents:
        FreeAgentSnapshot.objects.filter(league=league, captured_at__lt=cutoff).exclude(
            pk=latest_free_agents.pk
        ).delete()
    # Preserve the newest observation of each matchup, including previous weeks.
    keep_matchups = []
    for espn_id in (
        MatchupSnapshot.objects.filter(league=league).values_list("espn_id", flat=True).distinct()
    ):
        keep_matchups.append(
            MatchupSnapshot.objects.filter(league=league, espn_id=espn_id)
            .order_by("-captured_at")
            .values_list("pk", flat=True)
            .first()
        )
    MatchupSnapshot.objects.filter(league=league, captured_at__lt=cutoff).exclude(
        pk__in=keep_matchups
    ).delete()


@shared_task(ignore_result=True)
def sync_and_recommend():
    if settings.ESPN_TEAM_ID <= 0:
        raise ESPNError("Set ESPN_TEAM_ID to your team's positive ESPN ID.")
    try:
        with ESPNClient(
            settings.ESPN_LEAGUE_ID,
            settings.ESPN_SEASON,
            espn_s2=settings.ESPN_S2,
            swid=settings.ESPN_SWID,
        ) as client:
            league, team, _ = sync_league(client, team_id=settings.ESPN_TEAM_ID)
        decision = recommend_lineup(team.roster_snapshots.first())
        prune_snapshots(league, settings.SNAPSHOT_RETENTION_DAYS)
        return {"decision_id": decision.pk, "status": decision.recommendation["status"]}
    except Exception as exc:
        # Exception bodies may contain credentials; persist only the exception type.
        AuditEvent.objects.create(kind="sync.failed", details={"error_type": type(exc).__name__})
        raise
