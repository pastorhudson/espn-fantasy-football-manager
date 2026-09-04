"""Database lease shared by manual and scheduled synchronization."""

from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

from django.utils import timezone

from leagues.espn.client import ESPNError
from leagues.models import SyncLease


@contextmanager
def sync_lease(league_id, season):
    key = f"{league_id}:{season}"
    SyncLease.objects.get_or_create(key=key)
    token = uuid4()
    now = timezone.now()
    acquired = SyncLease.objects.filter(key=key, expires_at__lte=now).update(
        token=token, expires_at=now + timedelta(minutes=15)
    )
    if not acquired:
        raise ESPNError("A sync is already running for this league.")
    try:
        yield key, token
    finally:
        SyncLease.objects.filter(key=key, token=token).update(expires_at=timezone.now())
