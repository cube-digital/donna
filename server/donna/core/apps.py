from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "donna.core"
    label = "core"

    def ready(self):
        # No-op for now. The qdrant embedding warm-up from the original
        # docupal codebase was removed — Donna doesn't ship embeddings yet.
        # Re-introduce here when LLM/RAG infrastructure lands.
        return
