"""
Celery application for Donna.

`@shared_task` decorators across the codebase bind to this app. The integrations
app's ``apps.py:ready()`` auto-imports each connector's ``tasks.py`` so all tasks
are registered by the time workers start.

To run a worker locally::

    celery -A donna worker --loglevel=info

Settings are loaded from Django's ``CELERY_*`` settings (see donna/settings.py).
"""
from __future__ import annotations

import os

from celery import Celery


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "donna.settings")

app = Celery("donna")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Discover @shared_task in every INSTALLED_APP. Connector-owned tasks live
# in donna/integrations/connectors/<vendor>/<product>/tasks.py and are
# imported explicitly by donna.integrations.apps.IntegrationsConfig.ready();
# they bind to this app via @shared_task automatically.
app.autodiscover_tasks()
