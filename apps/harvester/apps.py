import os

from django.apps import AppConfig


class HarvesterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.harvester"
    label = "harvester"

    def ready(self):
        if os.environ.get("PIPELINE_WORKER") != "1":
            return
        # Only start in the actual server process, not the auto-reloader parent
        if os.environ.get("RUN_MAIN") != "true":
            return
        if getattr(self.__class__, "_started", False):
            return
        self.__class__._started = True

        import threading
        from .services.pipeline import HarvestManager

        threading.Thread(
            target=HarvestManager().run,
            daemon=True,
            name="harvest-manager",
        ).start()
