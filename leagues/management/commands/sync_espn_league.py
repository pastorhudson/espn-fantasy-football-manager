from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from leagues.espn.client import ESPNClient, ESPNError
from leagues.espn.sync import sync_league


class Command(BaseCommand):
    help = "Read ESPN league data and save local snapshots. Never modifies ESPN."

    def add_arguments(self, parser):
        parser.add_argument("--week", type=int)
        parser.add_argument("--free-agent-limit", type=int, default=100)
        parser.add_argument(
            "--check-auth", action="store_true", help="Check league access without saving data"
        )

    def handle(self, *args, **options):
        try:
            with ESPNClient(
                settings.ESPN_LEAGUE_ID,
                settings.ESPN_SEASON,
                espn_s2=settings.ESPN_S2,
                swid=settings.ESPN_SWID,
            ) as client:
                if options["check_auth"]:
                    client.check_authentication()
                    self.stdout.write("ESPN league access OK. No data saved.")
                    return
                if settings.ESPN_TEAM_ID <= 0:
                    raise ESPNError("Set ESPN_TEAM_ID to your team's positive ESPN ID.")
                league, team, matchups = sync_league(
                    client,
                    team_id=settings.ESPN_TEAM_ID,
                    week=options["week"],
                    free_agent_limit=options["free_agent_limit"],
                )
        except ESPNError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(f"{league} | {team.name} | scoring period {league.scoring_period}")
        scoring = league.settings.get("scoringSettings", {})
        self.stdout.write(f"Scoring: {scoring.get('scoringType', 'unspecified')}")
        for slot in team.roster_snapshots.first().slots.select_related("player"):
            projection = (
                "unavailable" if slot.projected_points is None else f"{slot.projected_points:.2f}"
            )
            self.stdout.write(
                f"  Slot {slot.lineup_slot_id}: {slot.player.name} | projection {projection} | {slot.injury_status or 'unknown'}"
            )
        for matchup in matchups:
            sides = [matchup.get("home", {}), matchup.get("away", {})]
            if any(side.get("teamId") == team.espn_id for side in sides):
                opponents = [
                    side["teamId"]
                    for side in sides
                    if side.get("teamId") not in (None, team.espn_id)
                ]
                self.stdout.write(
                    f"Matchup {matchup['id']}: opponent team IDs {opponents or 'bye'}"
                )
        self.stdout.write(self.style.SUCCESS("Read-only sync complete. No ESPN changes made."))
