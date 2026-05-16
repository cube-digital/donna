import copy
from rest_framework.routers import SimpleRouter as _SimpleRouter
from rest_framework_nested.routers import NestedSimpleRouter as _NestedSimpleRouter
from rest_framework_nested import routers


class SimpleRouter(_SimpleRouter):
    def extends(self, other: _SimpleRouter):
        if isinstance(other, routers.NestedSimpleRouter):
            self.urls.extend(other.urls)
            return

        self.urls.extend(other.urls)


class BulkSimpleRouter(_SimpleRouter):
    # Map http methods to actions defined on to bulk mixins
    routes = copy.deepcopy(_SimpleRouter.routes)
    routes[0].mapping.update(
        {
            "post": "bulk_create",
            "patch": "partial_bulk_update",
            "delete": "bulk_destroy",
        }
    )


class NestedBulkSimpleRouter(_NestedSimpleRouter):
    # Map http methods to actions defined on to bulk mixins
    routes = copy.deepcopy(_NestedSimpleRouter.routes)
    routes[0].mapping.update(
        {
            "post": "bulk_create",
            "patch": "partial_bulk_update",
            "delete": "bulk_destroy",
        }
    )
