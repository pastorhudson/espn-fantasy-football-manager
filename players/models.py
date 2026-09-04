from django.db import models


class Player(models.Model):
    # ESPN uses negative IDs for team defenses.
    espn_id = models.BigIntegerField(unique=True)
    name = models.CharField(max_length=255)
    position_id = models.PositiveSmallIntegerField()
    pro_team_id = models.PositiveSmallIntegerField(default=0)
    eligible_slots = models.JSONField(default=list)
    injury_status = models.CharField(max_length=40, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
