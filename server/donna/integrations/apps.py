from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    name = 'donna.integrations'

    def ready(self):
        from . import providers
        import importlib

        for provider in providers.all():
            importlib.import_module(provider.__module__)