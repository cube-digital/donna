"""Current-user profile API — ``/api/v1/users/me`` (+ picture upload).

User-scoped, not workspace-scoped: mounted under a path in the middleware's
IGNORED_PATHS so no ``X-Workspace-Id`` is required. Auth is the project-default
JWT; every action operates on ``request.user``.
"""
from __future__ import annotations

import uuid

from rest_framework import permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import MeSerializer


_MAX_PICTURE_BYTES = 5 * 1024 * 1024  # 5 MB
_ALLOWED_PICTURE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_EXT_BY_TYPE = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}


class MeView(APIView):
    """``GET`` / ``PATCH`` the signed-in user's profile."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(MeSerializer(request.user).data)

    def patch(self, request):
        serializer = MeSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class MePictureView(APIView):
    """``POST`` a new profile picture (multipart ``file``); ``DELETE`` to clear."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            return Response(
                {"detail": "No file provided (multipart field 'file')."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if upload.size > _MAX_PICTURE_BYTES:
            return Response(
                {"detail": "Picture must be 5 MB or smaller."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        content_type = (upload.content_type or "").lower()
        if content_type not in _ALLOWED_PICTURE_TYPES:
            return Response(
                {"detail": "Picture must be a PNG, JPEG, WebP, or GIF image."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = request.user
        # Stable-per-upload filename (uuid) so a new picture lands at a new key
        # and CDNs/browsers don't serve a stale cached image.
        ext = _EXT_BY_TYPE[content_type]
        old_name = user.picture.name if user.picture else None
        user.picture.save(f"{uuid.uuid4()}.{ext}", upload, save=True)
        if old_name and old_name != user.picture.name:
            user.picture.storage.delete(old_name)
        return Response(MeSerializer(user).data)

    def delete(self, request):
        user = request.user
        if user.picture:
            name = user.picture.name
            user.picture.delete(save=True)
            try:
                user.picture.storage.delete(name)
            except Exception:  # noqa: BLE001
                pass
        return Response(MeSerializer(user).data)
