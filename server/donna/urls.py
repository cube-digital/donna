from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularJSONAPIView, SpectacularSwaggerView


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", include("donna.status.urls")),
    path("api/auth/", include("donna.authentication.urls")),
    path("api/v1/", include("donna.workspaces.urls")),
    path("api/v1/", include("donna.integrations.urls")),
    path("api/v1/notifications/", include("donna.notifications.urls")),
    path("api/v1/chat/", include("donna.chat.urls")),

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
