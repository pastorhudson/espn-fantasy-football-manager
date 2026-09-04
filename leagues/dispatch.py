"""Shared enqueue gate for web requests and Celery beat.

The database claim precedes broker publication. Workers must claim its token before
performing any work, so duplicate delivery and expired messages become no-ops.
"""

from datetime import timedelta
from uuid import UUID, uuid4

from django.conf import settings
from django.utils import timezone
from django_celery_beat.models import PeriodicTask
from kombu.exceptions import OperationalError

from leagues.models import SyncLease, SyncRequest

QUEUE_TTL = timedelta(minutes=5)
RUN_TTL = timedelta(minutes=15)
COOLDOWN = timedelta(minutes=1)
SCHEDULE_WINDOW = timedelta(minutes=1)


def sync_key():
    if settings.ESPN_LEAGUE_ID <= 0 or settings.ESPN_TEAM_ID <= 0 or settings.ESPN_SEASON < 2019:
        return None
    return f"{settings.ESPN_LEAGUE_ID}:{settings.ESPN_SEASON}"


def scheduled_soon(now):
    task = PeriodicTask.objects.select_related("interval").filter(
        name="ESPN shadow sync", enabled=True,
        task__in=("leagues.tasks.schedule_sync", "leagues.tasks.sync_and_recommend"),
    ).first()
    if not task or not task.interval or (task.expires and task.expires <= now):
        return None
    if task.start_time and task.start_time > now:
        due = task.start_time
    elif task.last_run_at is None:
        # New schedules are dispatched on beat's next tick. Don't block forever
        # if beat isn't running; after a minute allow a manual recovery request.
        due = task.date_changed
    else:
        due = task.last_run_at + task.interval.schedule.run_every
        # Beat writes last_run_at when it publishes. Include its recent dispatch
        # window so a job waiting in Redis is covered before it reserves the DB row.
        if now - SCHEDULE_WINDOW <= task.last_run_at <= now:
            return task.last_run_at + SCHEDULE_WINDOW
    if now - SCHEDULE_WINDOW <= due <= now + SCHEDULE_WINDOW:
        return due + SCHEDULE_WINDOW
    return None


def update_status(*, check_schedule=True):
    now = timezone.now()
    key = sync_key()
    response = {"can_update": False, "phase": "unconfigured", "decision_id": None,
                "message": "Configure the ESPN league and team before updating."}
    if key is None:
        return response
    run = SyncRequest.objects.filter(key=key).first()
    if run:
        response.update(decision_id=run.decision_id)
        if run.status in ("queued", "running") and run.expires_at > now:
            return {**response, "phase": run.status,
                    "message": "Update queued; waiting for a worker." if run.status == "queued"
                    else "Updating league data and decisions…"}
    if SyncLease.objects.filter(key=key, expires_at__gt=now).exists():
        return {**response, "phase": "running", "message": "An ESPN sync is already running."}
    if run and run.cooldown_until > now:
        return {**response, "phase": "cooldown", "message": (
            "Update failed. You can retry in a minute." if run.status == "failed" else
            "Update completed. Please wait a minute before requesting another."
        )}
    if check_schedule and scheduled_soon(now):
        return {**response, "phase": "scheduled",
                "message": "A scheduled update is due shortly; no extra update is needed."}
    message = "Fetch fresh ESPN data and evaluate your lineup in the background."
    if run and run.status == "failed":
        message = "The last update failed. You can try again."
    elif run and run.status in ("queued", "running"):
        message = "The previous update timed out. You can try again."
    return {**response, "can_update": True, "phase": "ready", "message": message}


def reserve_update(*, check_schedule=True):
    status = update_status(check_schedule=check_schedule)
    if not status["can_update"]:
        return None, status
    key = sync_key()
    SyncRequest.objects.get_or_create(key=key)
    now = timezone.now()
    token = uuid4()
    # Compare-and-set is the authority, not the earlier UI/status read. Only one
    # caller wins even when multiple requests see the same idle state.
    claimed = SyncRequest.objects.filter(
        key=key, expires_at__lte=now, cooldown_until__lte=now,
    ).update(token=token, status="queued", requested_at=now,
             expires_at=now + QUEUE_TTL, decision_id=None)
    if not claimed:
        return None, update_status(check_schedule=check_schedule)
    return token, update_status(check_schedule=False)


def enqueue_update(*, check_schedule=True):
    from leagues.tasks import sync_and_recommend

    token, status = reserve_update(check_schedule=check_schedule)
    if token is None:
        return status
    try:
        sync_and_recommend.apply_async(
            kwargs={"reservation": str(token)}, task_id=str(token),
            expires=int(QUEUE_TTL.total_seconds()), retry=False,
        )
    except (OperationalError, OSError):
        # Publication can fail after Redis accepted a message. Invalidate the
        # token so such a message cannot execute, and throttle retries.
        now = timezone.now()
        cancelled = SyncRequest.objects.filter(
            key=sync_key(), token=token, status="queued",
        ).update(status="failed", expires_at=now, cooldown_until=now + COOLDOWN)
        if not cancelled:
            return update_status(check_schedule=False)
        return {**update_status(check_schedule=False),
                "message": "Could not queue the update. Please try again in a minute."}
    return status


def start_update(token):
    try:
        token = UUID(str(token))
    except (ValueError, TypeError, AttributeError):
        return False
    now = timezone.now()
    return bool(SyncRequest.objects.filter(
        key=sync_key(), token=token, status="queued", expires_at__gt=now,
    ).update(status="running", expires_at=now + RUN_TTL))


def finish_update(token, *, failed=False, decision_id=None):
    now = timezone.now()
    SyncRequest.objects.filter(key=sync_key(), token=token, status="running").update(
        status="failed" if failed else "succeeded", expires_at=now,
        cooldown_until=now + COOLDOWN, decision_id=decision_id,
    )
