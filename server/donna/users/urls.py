from __future__ import annotations

from django.urls import path

from donna.users.api.v1.views import MePictureView, MeView


urlpatterns = [
    path("users/me", MeView.as_view(), name="users-me"),
    path("users/me/picture", MePictureView.as_view(), name="users-me-picture"),
]
