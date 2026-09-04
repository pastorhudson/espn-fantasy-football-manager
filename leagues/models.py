from django.db import models
from django.utils import timezone


class League(models.Model):
    espn_id = models.PositiveBigIntegerField()
    season = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=255)
    settings = models.JSONField(default=dict)
    scoring_period = models.PositiveSmallIntegerField(default=0)
    matchup_period = models.PositiveSmallIntegerField(default=0)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["espn_id", "season"], name="unique_league_season")
        ]

    def __str__(self):
        return f"{self.name} ({self.season})"


class FantasyTeam(models.Model):
    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="teams")
    espn_id = models.PositiveIntegerField()
    name = models.CharField(max_length=255)
    owners = models.JSONField(default=list)
    preferences = models.JSONField(default=dict, blank=True)
    waiver_rank = models.PositiveIntegerField(null=True, blank=True)
    transaction_counters = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["league", "espn_id"], name="unique_team_league")
        ]

    def __str__(self):
        return self.name


class RosterSnapshot(models.Model):
    team = models.ForeignKey(FantasyTeam, on_delete=models.CASCADE, related_name="roster_snapshots")
    scoring_period = models.PositiveSmallIntegerField()
    captured_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-captured_at"]


class RosterSlot(models.Model):
    snapshot = models.ForeignKey(RosterSnapshot, on_delete=models.CASCADE, related_name="slots")
    player = models.ForeignKey("players.Player", on_delete=models.PROTECT)
    lineup_slot_id = models.PositiveSmallIntegerField()
    projected_points = models.FloatField(null=True, blank=True)
    actual_points = models.FloatField(null=True, blank=True)
    injury_status = models.CharField(max_length=40, blank=True)
    eligible_slots = models.JSONField(default=list)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["snapshot", "player"], name="unique_roster_player")
        ]


class MatchupSnapshot(models.Model):
    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="matchup_snapshots")
    espn_id = models.PositiveBigIntegerField()
    scoring_period = models.PositiveSmallIntegerField()
    matchup_period = models.PositiveSmallIntegerField()
    captured_at = models.DateTimeField(auto_now_add=True, db_index=True)
    data = models.JSONField(default=dict)


class FreeAgentSnapshot(models.Model):
    league = models.ForeignKey(
        League, on_delete=models.CASCADE, related_name="free_agent_snapshots"
    )
    scoring_period = models.PositiveSmallIntegerField()
    captured_at = models.DateTimeField(auto_now_add=True, db_index=True)
    # Store the bounded ESPN result and its limit; never imply this is the full pool.
    limit = models.PositiveIntegerField(default=100)
    data = models.JSONField(default=list)


class SyncLease(models.Model):
    key = models.CharField(max_length=80, primary_key=True)
    token = models.UUIDField(null=True)
    expires_at = models.DateTimeField(default=timezone.now)
