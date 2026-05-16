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


class KnowledgeLinkable:
    """
    Mixin for any model that can have knowledge items linked to it.

    The model must also declare::

        knowledge_links = GenericRelation(
            'knowledge.KnowledgeLink',
            content_type_field='entity_type',
            object_id_field='entity_id',
        )
    """

    def link_knowledge(self, item, role=""):
        from narrio.knowledge.models import KnowledgeLink

        return KnowledgeLink.objects.link(self, item, role)

    def unlink_knowledge(self, item, role=None):
        from narrio.knowledge.models import KnowledgeLink

        return KnowledgeLink.objects.unlink(self, item, role)

    def bulk_link_knowledge(self, items, role=""):
        from narrio.knowledge.models import KnowledgeLink

        return KnowledgeLink.objects.bulk_link(self, items, role)
