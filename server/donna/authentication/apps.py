from django.apps import AppConfig


class AuthenticationConfig(AppConfig):
    name = "donna.authentication"
    label = "authentication"

    def ready(self) -> None:  # pragma: no cover
        # Import receivers so the @receiver decorators register their connections.
        from . import receivers   # noqa: F401
