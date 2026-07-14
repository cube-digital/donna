from pathlib import Path

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path, re_path
from django.views.decorators.cache import never_cache
from drf_spectacular.views import SpectacularJSONAPIView, SpectacularSwaggerView

from donna.workspaces.urls import public_urlpatterns as workspaces_public_urls


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", include("donna.status.urls")),
    path("api/auth/", include("donna.authentication.urls")),
    path("api/v1/", include("donna.workspaces.urls")),
    # Public token-based invitation endpoints (no workspace tenancy);
    # bypasses WorkspaceMiddleware via IGNORED_PATHS.
    path("api/v1/", include((workspaces_public_urls, "workspaces"), namespace="workspaces_public")),
    path("api/v1/", include("donna.integrations.urls")),
    path("api/v1/notifications/", include("donna.notifications.urls")),
    path("api/v1/chat/", include("donna.chat.urls")),
    path("api/v1/cortex/", include("donna.cortex.urls")),
    path("api/v1/automation/", include("donna.automation.urls")),

    # API schema + Swagger UI. Always mounted; gate behind auth in prod
    # via SPECTACULAR_SETTINGS["SERVE_PERMISSIONS"] if needed.
    path(
        "swagger/",
        SpectacularSwaggerView.as_view(url_name="schema-swagger-json"),
        name="apidoc",
    ),
    path(
        "swagger/swagger.json/",
        SpectacularJSONAPIView.as_view(),
        name="schema-swagger-json",
    ),
]

if settings.DEBUG:
    urlpatterns += [
        # Serving Media
        *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
        *static(settings.STATIC_URL, document_root=settings.STATIC_ROOT),
    ]

# ── SPA catch-all (must be last) ────────────────────────────────────
# WhiteNoise serves the bundle's real files ("/", "/assets/*"). Client-side
# routes (e.g. /cortex, /channels) have no matching file, so they fall through
# to Django — return index.html and let the router take over. Only mounted when
# the built bundle is present (prod image); excludes the API / admin / docs /
# static / ws prefixes so a genuine 404 there is never masked by the SPA shell.
_WEB_DIST_ROOT = getattr(settings, "WHITENOISE_ROOT", None)
if _WEB_DIST_ROOT:
    _INDEX_HTML = (Path(_WEB_DIST_ROOT) / "index.html").read_bytes()

    @never_cache
    def spa_index(request):
        return HttpResponse(_INDEX_HTML, content_type="text/html")

    urlpatterns += [
        re_path(r"^(?!api/|admin/|swagger/|ws/|static/|favicon\.ico).*$", spa_index),
    ]
