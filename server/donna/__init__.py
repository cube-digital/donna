"""
Donna package init.

Re-exports the Celery app so ``@shared_task`` knows the default app and
``celery -A donna worker ...`` resolves the entry point.
"""
from .celery import app as celery_app


__all__ = ["celery_app"]
