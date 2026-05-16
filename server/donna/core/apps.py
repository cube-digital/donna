import os
import sys
import threading

from django.apps import AppConfig


def _is_server_process():
    """Return True when Django is running as a web server (not migrate, shell, etc.)."""
    if os.environ.get("RUN_MAIN") == "true":
        return True
    argv = sys.argv
    if not argv:
        return False
    command = os.path.basename(argv[0])
    if command in ("uvicorn", "gunicorn", "daphne"):
        return True
    if len(argv) > 1 and argv[1] == "runserver":
        return True
    return False


class CoreConfig(AppConfig):
    name = "docupal.core"

    def ready(self):
        if not _is_server_process():
            return

        thread = threading.Thread(
            target=self._warm_up, name="embedding-warmup", daemon=True
        )
        thread.start()

    @staticmethod
    def _warm_up():
        from docupal.core.logging import get_logger
        from docupal.core.qdrant_helpers.embeddings import warm_up_embeddings

        logger = get_logger(__name__)
        logger.info("warming_up_embeddings")
        warm_up_embeddings()
        logger.info("embeddings_ready")
