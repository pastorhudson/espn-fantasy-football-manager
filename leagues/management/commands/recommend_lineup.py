import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from decisions.lineup import recommend_lineup
from leagues.models import RosterSnapshot


class Command(BaseCommand):
    help = "Save a shadow lineup recommendation from the latest local roster."

    def handle(self, *args, **options):
        snapshot = RosterSnapshot.objects.filter(
            team__espn_id=settings.ESPN_TEAM_ID,
            team__league__espn_id=settings.ESPN_LEAGUE_ID,
            team__league__season=settings.ESPN_SEASON,
        ).first()
        if snapshot is None:
            raise CommandError("No roster snapshot. Run sync_espn_league first.")
        decision = recommend_lineup(snapshot)
        self.stdout.write(json.dumps(decision.recommendation, indent=2))
        self.stdout.write(f"Shadow decision {decision.pk} saved. No ESPN changes made.")
