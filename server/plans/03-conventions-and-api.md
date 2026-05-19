# Conventions and API surface

## Standard app layout

Every app follows this shape (workspaces is the reference):

```
<app>/
├── __init__.py
├── admin.py            # Django admin registrations
├── apps.py             # AppConfig (name = "donna.<app>")
├── models.py           # All models
├── services.py         # Business logic, extending BaseService
├── urls.py             # Router registration for this app's viewsets
├── migrations/
├── api/
│   └── v1/
│       ├── __init__.py
│       ├── filters.py
│       ├── serializers.py
│       └── views.py
└── tests/
    ├── __init__.py
    ├── factories.py
    ├── test_models.py
    ├── test_services.py
    └── test_views.py
```

**Rules:**
- The `api/v1/` namespace is forward-looking — when we break compat, `api/v2/` lives alongside.
- Cross-app imports go through the app's public surface (models, services). Don't reach into another app's `api/` from outside.
- Permission classes used by only one app live in `views.py`. When the same class is needed by 2+ apps, extract to `<app>/permissions.py` (no project-wide `permissions.py`).

## Service pattern (mandatory)

Every business operation goes through a service. Three rules:

1. **Each service inherits from `donna.core.services.BaseService[T]`** and sets `model_class = T`. BaseService provides default `create` / `update` / `delete` implementations and binds `current_user` + `company` (active workspace) from the request.

2. **Each ViewSet sets `service_class = <app>Service`.** The `ServiceMethodMixin` in `core/mixins.py` discovers methods on the service automatically:
   - `create_<model_name>(data)` → falls back to `create(data)`
   - `update_<model_name>(instance, data)` → falls back to `update(instance, data)`
   - `delete_<model_name>(instance)` → falls back to `delete(instance)`

3. **Services own all state mutations.** Views do request/response shaping; services own transactions, validation that crosses the serializer's reach, and side effects (membership seeding, ownership transfer, audit logging).

**`request.user` and `request.workspace` reach services via the constructor**, not magic globals. The mixin builds the service as `service_class(current_user=request.user, company=request.workspace)`. Services that don't have a workspace context (e.g., workspace creation) tolerate `self.company is None`.

### Documented exception — `integrations` app

The `integrations` app intentionally violates rule 2 (and partly rule 3) and uses `RegistryService` only for the connect/disconnect/list/callback flow. The webhook view and per-provider Celery tasks call the framework + DB directly without a service layer because the logic is genuinely thin (~4 lines per view action; tasks own their own orchestration). If/when integration logic grows enough to merit a service (e.g., cross-provider ingestion orchestration, complex retry/recovery), refactor back to a single `IngestionService`. See [05-integration-architecture.md](05-integration-architecture.md) and [04-roadmap.md](04-roadmap.md) for the rationale.

## Serializer pattern (read/write split)

Each ViewSet may set either `serializer_class` (single) or both `read_serializer_class` and `write_serializer_class` (split). The split is selected per resource by this rule:

> **Use read/write only when the shapes meaningfully diverge.** Otherwise the single `serializer_class` is enough.

The `core/generics.py:GenericAPIView` already supports both — `get_read_serializer` / `get_write_serializer` / `get_list_serializer` lookups exist with sensible fallbacks. The mixins call them correctly: `create` and `update` use the write serializer for input validation, then re-render via the read serializer for the response.

**When to split:**
- Response includes computed fields the request can't carry (e.g., `my_role` derived from current user).
- Response embeds related objects; request takes only foreign-key IDs (e.g., `WorkspaceMembership` write takes `user_id`, read embeds the user).
- Different field requirements between client → server vs server → client (most CRUD with rich reads).

**When NOT to split:**
- Both shapes are nearly identical, possibly differing in 1–2 fields. Use one `serializer_class` and mark fields `read_only=True` / `write_only=True` inline.

## ViewSet pattern

Inherit `donna.core.viewsets.ModelViewSet` (or `ReadOnlyModelViewSet`). Both already wire the service-aware mixins from `core/mixins.py`.

**Standard ViewSet contract:**
- `queryset` set on the class (DRF requires it for routers).
- `service_class` set on the class.
- Either `serializer_class` or `read_serializer_class` + `write_serializer_class`.
- `permission_classes` for the baseline.
- `permission_classes_by_method` (from `core/generics.py:GenericAPIView`) for HTTP-verb-specific overrides — used heavily because GET/POST/PATCH/DELETE often have different access rules.
- `get_queryset()` overridden to apply tenant scoping (`request.workspace`) and any per-action filtering (e.g., "my workspaces only" on list).
- `lookup_field` overridden when the URL identifies the resource by something other than its own UUID (e.g., `lookup_field = "user_id"` on `WorkspaceMembershipViewSet` so URLs read `/members/{user_uuid}/`).

**PATCH only, no PUT.** `UpdateModelMixin` in `core/mixins.py` exposes `partial_update` only — full-resource PUT is rejected. Smaller payloads, no "send the whole resource or nothing."

## Permission patterns

For multi-tenant access control, three reusable classes anchor most viewsets:

- **`IsWorkspaceMember`** — caller is a member of the active workspace (or of the target object's workspace).
- **`IsWorkspaceAdminOrOwner`** — caller has ADMIN or OWNER role in the active workspace.
- **`IsWorkspaceOwner`** — caller has OWNER role.

All three implement both `has_permission` (request-level, uses `request.workspace`) and `has_object_permission` (object-level, uses the target's workspace). Wired per HTTP method via `permission_classes_by_method`. Currently live inline in `workspaces/api/v1/views.py`; will extract to `workspaces/permissions.py` when chat needs them.

## Response envelope

Every successful response is wrapped by `core/renderers.py:StandardJSONRenderer`:

```json
{ "data": <payload>, "meta": {}, "message": "success", "code": 0 }
```

Paginated lists embed pagination metadata in `meta`. Errors go through `core/exception_handler.py:custom_exception_handler`, which maps DRF validation errors to a field-keyed shape:

```json
{
  "data": { "field": { "message": "...", "type": "validation_error" } },
  "meta": {},
  "message": "Validation Error",
  "code": 400
}
```

Pagination uses `core/pagination.py:StandardLimitOffsetPagination` — `?limit=100&offset=0`, max limit 500.

---

## API surface (workspaces + channels + members)

20 endpoints total. All under `/api/v1/`. Header-tenanted unless noted.

### Workspaces

| # | Method + Path | Tenant via | Purpose | Who can call |
|---|---|---|---|---|
| 1 | `POST /workspaces` | — | Create. Caller becomes OWNER. | Authenticated |
| 2 | `GET /workspaces` | — | List the caller's workspaces. | Authenticated |
| 3 | `GET /workspaces/{id}` | URL | Retrieve. | Member |
| 4 | `PATCH /workspaces/{id}` | URL | Update name/slug. | OWNER or ADMIN |
| 5 | `DELETE /workspaces/{id}` | URL | Delete (cascades). | OWNER only |

### Workspace members

| # | Method + Path | Tenant via | Purpose | Who can call |
|---|---|---|---|---|
| 6 | `POST /members` | Header | Invite a user. | OWNER or ADMIN |
| 7 | `GET /members` | Header | List members of active workspace. | Member |
| 8 | `GET /members/{user_id}` | Header | Retrieve one. | Member |
| 9 | `PATCH /members/{user_id}` | Header | Change role (incl. ownership transfer). | OWNER or ADMIN |
| 10 | `DELETE /members/{user_id}` | Header | Kick or self-leave. | ADMIN (others) or self |

Note: `lookup_field = "user_id"`. Membership IDs never appear in URLs — callers think in users.

### Channels (planned)

| # | Method + Path | Tenant via | Purpose | Who can call |
|---|---|---|---|---|
| 11 | `POST /channels` | Header | Create. Creator becomes channel ADMIN. | Workspace member |
| 12 | `GET /channels` | Header | List channels visible to caller (public + private-with-membership). | Workspace member |
| 13 | `GET /channels/{id}` | Header | Retrieve. 404 (not 403) for invisible-private. | Channel member or public |
| 14 | `PATCH /channels/{id}` | Header | Rename / retopic / change visibility. | Channel ADMIN |
| 15 | `DELETE /channels/{id}` | Header | Delete. Cascades. | Channel ADMIN or workspace OWNER |

### Channel members (planned)

| # | Method + Path | Tenant via | Purpose | Who can call |
|---|---|---|---|---|
| 16 | `POST /channels/{cid}/members` | Header | Self-join (public, no payload) or admin-add (private, `user_id`). | Self for public; ADMIN for private |
| 17 | `GET /channels/{cid}/members` | Header | List. | Channel member |
| 18 | `GET /channels/{cid}/members/{user_id}` | Header | Retrieve. | Channel member |
| 19 | `PATCH /channels/{cid}/members/{user_id}` | Header | Promote/demote within channel. | Channel ADMIN |
| 20 | `DELETE /channels/{cid}/members/{user_id}` | Header | Kick or self-leave. | ADMIN (others) or self |

---

## Routing

Two routers — flat for top-level resources, nested for channel→member chain:

```python
# workspaces/urls.py
router = SimpleRouter()
router.register(r"workspaces", WorkspaceViewSet)
router.register(r"members", WorkspaceMembershipViewSet)

# chat/urls.py (planned)
router.register(r"channels", ChannelViewSet)
channels_router = NestedSimpleRouter(router, r"channels", lookup="channel")
channels_router.register(r"members", ChannelMembershipViewSet)
```

`SimpleRouter` and `NestedSimpleRouter` come from `donna.core.routers` (which wraps `rest_framework_nested`). The workspace prefix is *not* in the URL because it's resolved from the header.

## Design decisions encoded above

- **Add vs join collapsed into one POST** (rows 16, 6) — keeps the URL surface small; the service routes on the request body + permissions. Splitting into `/join` and `/leave` actions is straightforward later if analytics or permission stories demand.
- **Visibility flip allowed on PATCH** (row 14) — non-trivial operation, the service should warn or require a confirmation flag. Alternative is to disallow visibility changes entirely and force "create new channel." We keep it allowed for now and gate it server-side.
- **404 vs 403 for unreachable private channels** (row 13) — leaking "this channel ID exists but you can't see it" is a real concern in multi-tenant. Always 404.
- **Membership lookups by user_id** (rows 8–10, 18–20) — Membership IDs are implementation noise.

## Open

- **Auth mechanism** — JWT vs Django session. Affects authentication classes, login/logout/refresh endpoints, and the SSE ticket exchange when realtime is added.
- **Bulk operations** — `core/mixins.py` has `BulkCreateModelMixin` and `BulkDestroyModelMixin`; not used yet but available when a real bulk use case appears.
- **Filtering** — `filters.py` per app stays empty until a real query parameter is needed.
- **Cursor pagination** — limit/offset is fine for v1; cursor pagination is a switch when message scrolls grow large.
