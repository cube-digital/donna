from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
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
