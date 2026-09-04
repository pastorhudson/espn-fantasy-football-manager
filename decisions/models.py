from django.core.validators import MinValueValidator
from django.db import models


class ManagerPolicy(models.Model):
    team = models.OneToOneField(
        "leagues.FantasyTeam", on_delete=models.CASCADE, related_name="policy"
    )
    autopilot_enabled = models.BooleanField(default=False)
    shadow_mode = models.BooleanField(default=True)
    protected_players = models.ManyToManyField("players.Player", blank=True)
    max_weekly_adds = models.PositiveSmallIntegerField(default=0)
    max_faab_per_player = models.DecimalField(
        max_digits=9, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    max_faab_per_week = models.DecimalField(
        max_digits=9, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    minimum_improvement = models.FloatField(default=2, validators=[MinValueValidator(0)])
    trades_require_approval = models.BooleanField(default=True)


class Decision(models.Model):
    team = models.ForeignKey("leagues.FantasyTeam", on_delete=models.PROTECT)
    roster_snapshot = models.ForeignKey(
        "leagues.RosterSnapshot", on_delete=models.PROTECT, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    kind = models.CharField(max_length=40)
    rationale = models.TextField()
    recommendation = models.JSONField(default=dict)
    shadow_mode = models.BooleanField(default=True)
