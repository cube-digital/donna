"""DRF mixins that delegate CRUD to :class:`docupal.core.services.BaseService` methods."""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.settings import api_settings


class ServiceMethodMixin:
    """Discover and call service methods from view actions.

    Resolution order (similar to DRF ``validate_<field>``):

    1. ``<action>_<model_name>`` (e.g. ``create_workspace``).
    2. ``<action>`` (e.g. ``create``).

    If no matching method exists, mixins fall back to serializer save / model defaults.
    """

    def get_service(self):
        """Build a service instance with ``current_user`` and ``company`` from the request.

        Returns:
            An instance of ``service_class``, or ``None`` if the view has no
            ``service_class``.

        Note:
            ``company`` is set from ``request.company`` (active workspace) when
            :class:`~docupal.workspaces.middlewares.WorkspaceMiddleware` has run.
        """
        service_class = getattr(self, "service_class", None)
        if service_class is None:
            return None

        # Pass current user if request is available and user is authenticated
        current_user = None
        company = None
        request = getattr(self, "request", None)

        if request:
            if hasattr(request, "user") and request.user.is_authenticated:
                current_user = request.user
            if hasattr(request, "company"):
                company = request.company

        return service_class(current_user=current_user, company=company)

    def get_model_name(self):
        """Return the queryset model's short name (e.g. ``Workspace`` -> ``workspace``)."""
        queryset = self.get_queryset()
        if queryset is not None:
            return queryset.model._meta.model_name
        return None

    def get_service_method(self, action):
        """Return the bound service method for ``action``, or ``None``.

        Args:
            action: View action name (e.g. ``"create"``, ``"update"``, ``"delete"``).

        Returns:
            Callable on the service, or ``None`` if not defined.
        """
        service = self.get_service()
        if service is None:
            return None

        model_name = self.get_model_name()

        # Try specific method first: create_tour, update_client, etc.
        if model_name:
            specific_method_name = f"{action}_{model_name}"
            method = getattr(service, specific_method_name, None)
            if callable(method):
                return method

        # Fall back to generic method: create, update, etc.
        generic_method = getattr(service, action, None)
        if callable(generic_method):
            return generic_method

        return None


class CreateModelMixin(ServiceMethodMixin):
    """
    Create a model instance.
    """

    def create(self, request, *args, **kwargs):
        write_serializer = self.get_write_serializer(data=request.data)
        write_serializer.is_valid(raise_exception=True)
        instance = self.perform_create(write_serializer)

        read_serializer = self.get_read_serializer(instance)
        headers = self.get_success_headers(read_serializer.data)

        return Response(
            read_serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )

    def perform_create(self, serializer):
        service_method = self.get_service_method("create")
        if service_method:
            return service_method(serializer.validated_data)
        return serializer.save()

    def get_success_headers(self, data):
        try:
            return {"Location": str(data[api_settings.URL_FIELD_NAME])}
        except (TypeError, KeyError):
            return {}


class BulkCreateModelMixin(ServiceMethodMixin):
    """
    Bulk create a set of instances.
    """

    def bulk_create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        instances = self.perform_bulk_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )

    def perform_bulk_create(self, serializer):
        service_method = self.get_service_method("bulk_create")
        if service_method:
            return service_method(serializer.validated_data)
        return serializer.save()

    def get_success_headers(self, data):
        try:
            return {"Location": str(data[api_settings.URL_FIELD_NAME])}
        except (TypeError, KeyError):
            return {}


class ListModelMixin:
    """
    List a queryset.
    """

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_list_serializer(page)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_list_serializer(queryset)
        return Response(serializer.data)


class RetrieveModelMixin:
    """
    Retrieve a model instance.
    """

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_read_serializer(instance)
        return Response(serializer.data)


class UpdateModelMixin(ServiceMethodMixin):
    """
    Update a model instance.
    """

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        write_serializer = self.get_write_serializer(
            instance, data=request.data, partial=True
        )
        write_serializer.is_valid(raise_exception=True)

        instance = self.perform_update(write_serializer, instance)

        if getattr(instance, "_prefetched_objects_cache", None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            instance._prefetched_objects_cache = {}

        read_serializer = self.get_read_serializer(instance)

        return Response(read_serializer.data)

    def perform_update(self, serializer, instance=None):
        service_method = self.get_service_method("update")
        if service_method:
            # Pass instance and validated data to service
            return service_method(instance, serializer.validated_data)
        return serializer.save()


class DestroyModelMixin(ServiceMethodMixin):
    """
    Destroy a model instance.
    """

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def perform_destroy(self, instance):
        service_method = self.get_service_method("delete")
        if service_method:
            return service_method(instance)
        return instance.delete()


class BulkDestroyModelMixin(ServiceMethodMixin):
    """
    Bulk delete a set of instances.
    """

    def bulk_destroy(self, request, *args, **kwargs):
        ids = request.data

        if not ids or not isinstance(ids, list):
            return Response(
                {"error": "A list of IDs is required in the request body"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = self.get_queryset().filter(id__in=ids)

        if queryset.count() != len(ids):
            return Response(
                "Some resources could not be found", status=status.HTTP_404_NOT_FOUND
            )

        self.perform_bulk_destroy(queryset)

        return Response(status=status.HTTP_204_NO_CONTENT)

    def perform_bulk_destroy(self, queryset):
        service_method = self.get_service_method("bulk_delete")
        if service_method:
            return service_method(queryset)
        queryset.delete()
