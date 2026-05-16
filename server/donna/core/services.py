"""
Base service classes with common CRUD operations.
"""

from typing import TypeVar, Generic, Dict, Any, Type, Optional

from django.core.exceptions import ValidationError
from django.db import models, transaction
from rest_framework.exceptions import ValidationError as DRFValidationError


T = TypeVar("T", bound=models.Model)


class BaseService(Generic[T]):
    """
    Base service class providing common CRUD operations.

    Usage:
        class ClientService(BaseService[Client]):
            model_class = Client  # Required for create method

        # Then use:
        service = ClientService(current_user=request.user)
        client = service.create({"name": "Test", "customer_no": "001"})
        client = service.update(client, {"name": "Updated"})
        service.delete(client)
    """

    # Subclasses should set this to enable create method
    model_class: Type[T] = None

    def __init__(self, current_user: Optional["User"] = None, company: Optional["Company"] = None):
        """Initialize the service with request-scoped context.

        Args:
            current_user: Authenticated user from the request, when available.
            company: Active workspace/tenant from middleware (``request.company``),
                used by workspace-scoped create/update helpers.
        """
        self.current_user = current_user
        self.company = company

    def create(self, data: Dict[str, Any]) -> T:
        """
        Create a new model instance.

        Args:
            data: Dictionary of field values for the new instance

        Returns:
            The created model instance

        Raises:
            ValidationError: If creation fails or model_class is not set
        """
        if self.model_class is None:
            raise ValidationError(
                f"{self.__class__.__name__} must set model_class attribute to use create method"
            )

        if not data or not isinstance(data, dict):
            raise ValidationError("data must be a non-empty dictionary")

        if self.current_user and hasattr(self.model_class, "created_by"):
            data.setdefault("created_by", self.current_user)
        if self.current_user and hasattr(self.model_class, "modified_by"):
            data.setdefault("modified_by", self.current_user)

        try:
            instance = self.model_class.objects.create(**data)
            return instance
        except ValidationError:
            raise
        except TypeError as e:
            # Handle invalid field names
            raise ValidationError(f"Invalid fields in data: {str(e)}")
        except Exception as e:
            model_name = self.model_class.__name__.lower()
            raise ValidationError(f"Failed to create {model_name}: {str(e)}")

    def update(self, instance: T, data: Dict[str, Any]) -> T:
        """
        Update a model instance.

        Args:
            instance: The model instance to update
            data: Dictionary of field values to update

        Returns:
            The updated model instance

        Raises:
            ValidationError: If update fails or instance is invalid
        """
        # Validate instance
        if instance is None:
            raise ValidationError("Cannot update None instance")

        if not isinstance(instance, models.Model):
            raise ValidationError(
                f"Expected Django model instance, got {type(instance).__name__}"
            )

        if not isinstance(data, dict):
            raise DRFValidationError("data must be a dictionary")

        try:
            for field, value in data.items():
                # Validate field exists on model
                if not hasattr(instance, field):
                    model_name = instance.__class__.__name__
                    raise ValidationError(f"Model {model_name} has no field '{field}'")
                setattr(instance, field, value)

            instance.save()
            return instance
        except ValidationError:
            raise
        except Exception as e:
            model_name = instance.__class__.__name__.lower()
            raise ValidationError(f"Failed to update {model_name}: {str(e)}")

    def delete(self, instance: T) -> bool:
        """
        Delete a model instance.

        Args:
            instance: The model instance to delete

        Returns:
            True if deletion was successful

        Raises:
            ValidationError: If deletion fails or instance is invalid
        """
        # Validate instance
        if instance is None:
            raise ValidationError("Cannot delete None instance")

        # Check if instance is a Django model
        if not isinstance(instance, models.Model):
            raise ValidationError(
                f"Expected Django model instance, got {type(instance).__name__}"
            )

        # Check if instance has delete method
        if not hasattr(instance, "delete") or not callable(getattr(instance, "delete")):
            model_name = instance.__class__.__name__
            raise ValidationError(
                f"Model {model_name} does not have a callable delete method"
            )

        try:
            instance.delete()
            return True
        except Exception as e:
            model_name = instance.__class__.__name__.lower()
            raise ValidationError(f"Failed to delete {model_name}: {str(e)}")
