import uuid

from django.db import models


class RosterAction(models.Model):
    class Status(models.TextChoices):
        PROPOSED = "proposed"
        APPROVED = "approved"
        ATTEMPTED = "attempted"
        COMPLETED = "completed"
        FAILED = "failed"

    decision = models.ForeignKey(
        "decisions.Decision", on_delete=models.PROTECT, related_name="actions"
    )
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROPOSED)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class AuditEvent(models.Model):
    league = models.ForeignKey("leagues.League", on_delete=models.PROTECT, null=True, blank=True)
    action = models.ForeignKey(RosterAction, on_delete=models.PROTECT, null=True, blank=True)
    kind = models.CharField(max_length=60, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    details = models.JSONField(default=dict)
