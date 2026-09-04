from django.core.management.base import BaseCommand, CommandError
from django_celery_beat.models import IntervalSchedule, PeriodicTask


class Command(BaseCommand):
    help = "Install/update the read-only sync schedule (run one beat process)."

    def add_arguments(self, parser):
        parser.add_argument("--minutes", type=int, default=30)
        parser.add_argument("--disable", action="store_true")

    def handle(self, *args, **options):
        if options["minutes"] < 5:
            raise CommandError("Sync interval must be at least five minutes.")
        interval, _ = IntervalSchedule.objects.get_or_create(
            every=options["minutes"], period=IntervalSchedule.MINUTES
        )
        task, _ = PeriodicTask.objects.update_or_create(
            name="ESPN shadow sync",
            defaults={
                "task": "leagues.tasks.sync_and_recommend",
                "interval": interval,
                "crontab": None,
                "solar": None,
                "clocked": None,
                "args": "[]",
                "kwargs": "{}",
                "enabled": not options["disable"],
                "expire_seconds": options["minutes"] * 60,
            },
        )
        self.stdout.write(f"ESPN shadow sync: {'enabled' if task.enabled else 'disabled'}.")
