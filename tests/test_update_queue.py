from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.apps import apps
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django_celery_beat.models import IntervalSchedule, PeriodicTask
from kombu.exceptions import OperationalError

from leagues.dispatch import (
    enqueue_update,
    finish_update,
    reserve_update,
    start_update,
    sync_key,
    update_status,
)
from leagues.espn.client import ESPNError
from leagues.models import SyncLease, SyncRequest
from leagues.tasks import schedule_sync, sync_and_recommend
from roster_actions.models import AuditEvent

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def configured(settings):
    settings.ESPN_LEAGUE_ID = 123
    settings.ESPN_TEAM_ID = 1
    settings.ESPN_SEASON = 2026


def schedule(last_run_at, **kwargs):
    interval = IntervalSchedule.objects.create(every=30, period=IntervalSchedule.MINUTES)
    return PeriodicTask.objects.create(
        name="ESPN shadow sync", task="leagues.tasks.schedule_sync",
        interval=interval, last_run_at=last_run_at, **kwargs,
    )


def test_repeated_clicks_and_scheduled_dispatch_publish_once(admin_client):
    with patch("leagues.tasks.sync_and_recommend.apply_async") as publish:
        for _ in range(5):
            assert admin_client.post(reverse("decision-update")).status_code == 302
        assert schedule_sync()["phase"] == "queued"
        publish.assert_called_once()
        run = SyncRequest.objects.get()
        assert publish.call_args.kwargs["kwargs"] == {"reservation": str(run.token)}
    assert run.status == "queued"
    assert update_status()["can_update"] is False
    assert sync_and_recommend()["status"] == "skipped"
    assert admin_client.get(reverse("decision-update-status")).json()["phase"] == "queued"


def test_atomic_gate_rejects_stale_idle_read():
    # Simulate both callers reading idle before the winner commits its reservation.
    idle = {"can_update": True, "phase": "ready"}
    with patch("leagues.dispatch.update_status", return_value=idle):
        first, _ = reserve_update()
        second, _ = reserve_update()
    assert first is not None
    assert second is None
    assert SyncRequest.objects.get().token == first


def test_duplicate_delivery_expiry_and_old_completion_are_fenced():
    first, _ = reserve_update()
    assert start_update(first)
    assert not start_update(first)
    assert not start_update("bad-token")
    assert not start_update(uuid4())
    SyncRequest.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    second, _ = reserve_update()
    assert second != first
    assert not start_update(first)
    finish_update(first, decision_id=100)
    assert SyncRequest.objects.get().status == "queued"
    assert start_update(second)
    finish_update(second, decision_id=200)
    assert update_status()["phase"] == "cooldown"
    assert update_status()["decision_id"] == 200
    SyncRequest.objects.update(cooldown_until=timezone.now() - timedelta(seconds=1))
    assert update_status()["can_update"]


@pytest.mark.parametrize("seconds_ago,blocked", [(1770, True), (1800, True), (1850, True),
                                                (1930, False), (60 * 20, False), (0, True)])
def test_imminent_and_recent_schedule_guard(seconds_ago, blocked):
    schedule(timezone.now() - timedelta(seconds=seconds_ago))
    with patch("leagues.tasks.sync_and_recommend.apply_async") as publish:
        result = enqueue_update()
    assert (result["phase"] == "scheduled") is blocked
    assert publish.call_count == (0 if blocked else 1)


def test_new_disabled_expired_and_future_schedule():
    task = schedule(None)
    assert update_status()["phase"] == "scheduled"
    task.enabled = False
    task.save()
    assert update_status()["can_update"]
    task.enabled = True
    task.expires = timezone.now() - timedelta(seconds=1)
    task.save()
    assert update_status()["can_update"]
    task.expires = None
    task.start_time = timezone.now() + timedelta(minutes=10)
    task.save()
    assert update_status()["can_update"]


def test_schedule_does_not_block_its_own_dispatch():
    schedule(timezone.now())
    with patch("leagues.tasks.sync_and_recommend.apply_async") as publish:
        assert schedule_sync()["phase"] == "queued"
        publish.assert_called_once()


def test_manual_sync_lease_blocks_button():
    SyncLease.objects.create(key=sync_key(), expires_at=timezone.now() + timedelta(minutes=5))
    with patch("leagues.tasks.sync_and_recommend.apply_async") as publish:
        assert enqueue_update()["phase"] == "running"
        publish.assert_not_called()


def test_broker_failure_invalidates_token_and_throttles_retry():
    with patch("leagues.tasks.sync_and_recommend.apply_async", side_effect=OperationalError("secret")):
        status = enqueue_update()
    run = SyncRequest.objects.get()
    assert run.status == "failed"
    assert not start_update(run.token)
    assert status["phase"] == "cooldown"
    assert "secret" not in status["message"]
    with patch("leagues.tasks.sync_and_recommend.apply_async") as publish:
        enqueue_update()
        publish.assert_not_called()


def test_uncertain_publish_does_not_release_a_running_worker():
    def publish(**kwargs):
        assert start_update(kwargs["kwargs"]["reservation"])
        raise OperationalError("lost acknowledgment")
    with patch("leagues.tasks.sync_and_recommend.apply_async", side_effect=publish):
        assert enqueue_update()["phase"] == "running"
    assert SyncRequest.objects.get().status == "running"


def test_worker_completion_and_failure_cleanup():
    token, _ = reserve_update()
    fake_team = SimpleNamespace(roster_snapshots=SimpleNamespace(first=lambda: object()))
    fake_decision = SimpleNamespace(pk=42, recommendation={"status": "unchanged"})
    with (
        patch("leagues.tasks.ESPNClient"),
        patch("leagues.tasks.sync_league", return_value=(object(), fake_team, [])),
        patch("leagues.tasks.recommend_lineup", return_value=fake_decision),
        patch("leagues.tasks.prune_snapshots"),
    ):
        assert sync_and_recommend(reservation=str(token))["decision_id"] == 42
        assert sync_and_recommend(reservation=str(token))["status"] == "skipped"
    assert SyncRequest.objects.get().status == "succeeded"
    assert update_status()["phase"] == "cooldown"
    SyncRequest.objects.update(cooldown_until=timezone.now() - timedelta(seconds=1))
    token, _ = reserve_update()
    with patch("leagues.tasks.ESPNClient", side_effect=ESPNError("secret body")):
        with pytest.raises(ESPNError):
            sync_and_recommend(reservation=str(token))
    assert SyncRequest.objects.get().status == "failed"
    assert AuditEvent.objects.get(kind="sync.failed").details == {"error_type": "ESPNError"}


def test_permissions_csrf_and_gets_are_read_only(client, admin_user, django_user_model):
    url = reverse("decision-update")
    assert client.post(url).status_code == 302
    user = django_user_model.objects.create_user("viewer")
    user.user_permissions.add(Permission.objects.get(codename="view_decision"))
    client.force_login(user)
    assert client.post(url).status_code == 403
    user.user_permissions.add(Permission.objects.get(codename="request_sync"))
    assert client.get(url).status_code == 405
    response = client.get(reverse("decision-update-status"))
    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]
    assert not SyncRequest.objects.exists()
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(admin_user)
    assert strict.post(url).status_code == 403
    with patch("leagues.tasks.sync_and_recommend.apply_async") as publish:
        assert client.post(url).status_code == 302
        publish.assert_called_once()


def test_unconfigured_and_ui_state(settings, admin_client):
    settings.ESPN_TEAM_ID = 0
    assert update_status()["phase"] == "unconfigured"
    with patch("leagues.tasks.sync_and_recommend.apply_async") as publish:
        admin_client.post(reverse("decision-update"))
        publish.assert_not_called()
    settings.ESPN_TEAM_ID = 1
    token, _ = reserve_update()
    assert token
    content = admin_client.get(reverse("decision-list")).content.decode()
    assert 'id="update-button" type="submit" disabled' in content
    assert 'Update queued; waiting for a worker.' in content


def test_schedule_migration_preserves_preferences():
    task = schedule(timezone.now() - timedelta(minutes=10), enabled=False)
    task.task = "leagues.tasks.sync_and_recommend"
    task.save()
    original_last_run = task.last_run_at
    module = import_module("leagues.migrations.0004_syncrequest")
    module.forwards(apps, SimpleNamespace(connection=SimpleNamespace(alias="default")))
    task.refresh_from_db()
    assert task.task == "leagues.tasks.schedule_sync"
    assert not task.enabled
    assert task.interval.every == 30
    assert task.last_run_at == original_last_run
    call_command("configure_sync_schedule", minutes=5)
    task.refresh_from_db()
    assert task.task == "leagues.tasks.schedule_sync"
