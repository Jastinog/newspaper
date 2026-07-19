import logging

from django.core.management.base import BaseCommand

from apps.harvester.apps import _acquire_singleton_lock

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the harvester pipeline daemon (fetch feeds → extract content → images)."

    def handle(self, *args, **options):
        # Same Postgres advisory lock the in-process worker uses, so this daemon
        # and any PIPELINE_WORKER runserver can never both drive the pipeline.
        lock_conn = _acquire_singleton_lock()
        if lock_conn is None:
            self.stderr.write("Harvester already running in another process; exiting.")
            return
        # Keep the connection referenced for the process lifetime → lock stays held.
        self._lock_conn = lock_conn

        from apps.harvester.services.pipeline import HarvestManager

        self.stdout.write(self.style.SUCCESS("Harvester daemon starting…"))
        HarvestManager().run()
