import logging
import os

from django.apps import AppConfig

logger = logging.getLogger(__name__)

# Fixed 64-bit key for the process-wide Postgres advisory lock that guards the
# harvester singleton. Any constant works as long as nothing else in the DB
# reuses it. ("HARV" as ASCII bytes.)
HARVEST_LOCK_KEY = 0x48415256


def _acquire_singleton_lock():
    """Try to grab the harvester advisory lock on a dedicated, long-lived
    connection. Returns that connection (keep the reference alive so the session
    — and thus the lock — persists), or None if another process already holds it.

    A separate connection is used on purpose: it is not registered in
    `connections.all()`, so `close_old_connections` never closes it out from
    under us, and the session-level lock is held for the process's whole life.
    """
    from django.db import connections

    conn = connections.create_connection("default")
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", [HARVEST_LOCK_KEY])
        acquired = cur.fetchone()[0]
    if not acquired:
        conn.close()
        return None
    return conn


class HarvesterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.harvester"
    label = "harvester"

    _lock_conn = None

    def ready(self):
        if os.environ.get("PIPELINE_WORKER") != "1":
            return
        # Only start in the actual server process, not the auto-reloader parent
        if os.environ.get("RUN_MAIN") != "true":
            return
        if getattr(self.__class__, "_started", False):
            return

        # Cross-process guard: a Postgres advisory lock ensures exactly one
        # harvester runs even if several processes clear the checks above.
        lock_conn = _acquire_singleton_lock()
        if lock_conn is None:
            logger.info("Harvester already running in another process; not starting")
            return

        self.__class__._lock_conn = lock_conn  # keep alive → lock stays held
        self.__class__._started = True

        import threading
        from .services.pipeline import HarvestManager

        threading.Thread(
            target=HarvestManager().run,
            daemon=True,
            name="harvest-manager",
        ).start()
