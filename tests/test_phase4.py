from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone
from django_celery_beat.models import PeriodicTask

from decisions.lineup import recommend_lineup
from decisions.models import Decision
from leagues.espn.client import ESPNError
from leagues.locking import sync_lease
from leagues.models import FantasyTeam, League, RosterSlot, RosterSnapshot
from leagues.tasks import prune_snapshots, sync_and_recommend
from players.models import Player
from roster_actions.models import AuditEvent, RosterAction

pytestmark = pytest.mark.django_db


@pytest.fixture
def roster():
    league = League.objects.create(
        espn_id=123,
        season=2026,
        name="Test",
        scoring_period=1,
        settings={"rosterSettings": {"lineupSlotCounts": {"2": 1, "23": 1, "20": 3}}},
    )
    team = FantasyTeam.objects.create(league=league, espn_id=1, name="Test")
    snapshot = RosterSnapshot.objects.create(team=team, scoring_period=1)
    for pid, slot, points, eligible in [
        (1, 2, 10, [2, 23]),
        (2, 23, 8, [4, 23]),
        (3, 20, 20, [2, 23]),
    ]:
        player = Player.objects.create(espn_id=pid, name=f"Player {pid}", position_id=2)
        RosterSlot.objects.create(
            snapshot=snapshot,
            player=player,
            lineup_slot_id=slot,
            projected_points=points,
            eligible_slots=eligible,
        )
    return snapshot


def test_global_flex_assignment_and_idempotence(roster):
    decision = recommend_lineup(roster)
    assert decision.recommendation["projected_total"] == 30
    assert decision.recommendation["improvement"] == 12
    assert {a["player_id"] for a in decision.recommendation["assignments"]} == {1, 3}
    assert recommend_lineup(roster).pk == decision.pk
    assert Decision.objects.count() == 1
    assert decision.shadow_mode
    assert not RosterAction.objects.exists()


@pytest.mark.parametrize("value", [None, float("inf")])
def test_unknown_projection_blocks(roster, value):
    roster.slots.filter(player__espn_id=3).update(projected_points=value)
    assert recommend_lineup(roster).recommendation["status"] == "blocked"


def test_out_player_excluded(roster):
    roster.slots.filter(player__espn_id=3).update(injury_status="OUT")
    assert recommend_lineup(roster).recommendation["projected_total"] == 18


def test_stale_snapshot_blocks(roster):
    RosterSnapshot.objects.filter(pk=roster.pk).update(
        captured_at=timezone.now() - timedelta(hours=3)
    )
    assert recommend_lineup(roster).recommendation["status"] == "blocked"


def test_missing_rules_and_impossible_assignment(roster):
    roster.team.league.settings = {}
    roster.team.league.save()
    assert recommend_lineup(roster).recommendation["status"] == "blocked"


def test_lease_excludes_overlap_and_releases_on_error():
    with pytest.raises(ValueError), sync_lease(123, 2026):
        with pytest.raises(ESPNError, match="already running"):
            with sync_lease(123, 2026):
                pass
        raise ValueError()
    with sync_lease(123, 2026):
        pass


def test_schedule_is_opt_in_and_idempotent():
    assert not PeriodicTask.objects.exists()
    call_command("configure_sync_schedule", stdout=StringIO())
    call_command("configure_sync_schedule", minutes=15, stdout=StringIO())
    assert PeriodicTask.objects.count() == 1
    task = PeriodicTask.objects.get()
    assert task.enabled and task.interval.every == 15
    call_command("configure_sync_schedule", disable=True, stdout=StringIO())
    task.refresh_from_db()
    assert not task.enabled


def test_retention_preserves_evidence_and_latest(roster):
    recommend_lineup(roster)
    old = RosterSnapshot.objects.create(team=roster.team, scoring_period=1)
    latest = RosterSnapshot.objects.create(team=roster.team, scoring_period=1)
    RosterSnapshot.objects.all().update(captured_at=timezone.now() - timedelta(days=60))
    # Ordering is explicit to distinguish the latest observation.
    RosterSnapshot.objects.filter(pk=latest.pk).update(
        captured_at=timezone.now() - timedelta(days=40)
    )
    prune_snapshots(roster.team.league)
    assert RosterSnapshot.objects.filter(pk=roster.pk).exists()
    assert RosterSnapshot.objects.filter(pk=latest.pk).exists()
    assert not RosterSnapshot.objects.filter(pk=old.pk).exists()


def test_task_saves_shadow_decision(roster, settings):
    settings.ESPN_TEAM_ID = 1
    with (
        patch("leagues.tasks.ESPNClient"),
        patch("leagues.tasks.sync_league", return_value=(roster.team.league, roster.team, [])),
    ):
        result = sync_and_recommend()
    assert result["decision_id"] == Decision.objects.get().pk


def test_task_failure_audit_is_sanitized(settings):
    settings.ESPN_TEAM_ID = 1
    with patch("leagues.tasks.ESPNClient", side_effect=ESPNError("secret cookie")):
        with pytest.raises(ESPNError):
            sync_and_recommend()
    assert AuditEvent.objects.get().details == {"error_type": "ESPNError"}


def test_expired_sync_cannot_persist():
    from leagues.espn.sync import _persist
    from leagues.models import SyncLease

    with sync_lease(123, 2026) as lease:
        SyncLease.objects.filter(key=lease[0]).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        with pytest.raises(ESPNError, match="expired"):
            _persist(None, {}, 1, 1, 1, [], [], [], 100, lease)
    assert not League.objects.exists()


def test_ir_player_not_promoted_and_zero_is_flagged(roster):
    roster.slots.filter(player__espn_id=3).update(lineup_slot_id=21)
    roster.slots.filter(player__espn_id=2).update(projected_points=0)
    result = recommend_lineup(roster).recommendation
    assert result["projected_total"] == 10
    assert any("zero projection" in warning for warning in result["warnings"])
    assert 3 not in {a["player_id"] for a in result["assignments"]}
