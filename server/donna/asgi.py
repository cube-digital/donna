"""
ASGI config for donna project.

Routes HTTP through Django's standard ASGI app and WebSocket through
Django Channels' ``URLRouter``. Both protocols are served by the same
uvicorn process. JWT authentication for WebSocket connections lives in
``donna.chat.auth.SubprotocolJWTAuthMiddlewareStack``.

See plans/10-realtime-layer.md for the realtime architecture.
"""
from __future__ import annotations

import os

from django.core.asgi import get_asgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "donna.settings")

# IMPORTANT — get_asgi_application() must run before importing Channels +
# the chat routing module, because the routing module imports models
# (via consumers) and Django's app registry must be ready first.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from donna.chat.auth import SubprotocolJWTAuthMiddlewareStack  # noqa: E402
from donna.chat.routing import websocket_urlpatterns  # noqa: E402


application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            SubprotocolJWTAuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
