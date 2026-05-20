from django.contrib.auth import get_user_model
from django.db import models


class TimestampsMixin(models.Model):
    """
    Mixin that adds timestamp information to all models, more specifically
    when the entity was created and when it was last updated.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UserAuditMixin(models.Model):
    """
    Mixin that adds user audit information to all models, more specifically
    who owns(created) the entity and who was the last editor.
    """

    created_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        editable=False,
        related_name="created_%(app_label)s_%(class)s",
    )

    modified_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        related_name="modified_%(app_label)s_%(class)s",
    )

    class Meta:
        abstract = True


# KnowledgeLinkable was a copy-paste from the original `narrio` codebase that
# imported a non-existent `narrio.knowledge.models.KnowledgeLink`. Donna does
# not ship a knowledge-link generic relation. Removed per Phase 0 cleanup
# (see plans/04-roadmap.md). Re-introduce here if a real knowledge-link
# pattern is needed across multiple apps.
