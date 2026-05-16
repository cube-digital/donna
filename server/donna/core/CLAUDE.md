# Core Module

This is the shared foundation — all apps import from here. Do NOT duplicate or reimplement what already exists.

## What Lives Here

| Module | Purpose | Use It When |
|--------|---------|-------------|
| `services.py` | `BaseService` with CRUD | Every app's `services.py` |
| `generics.py` | `GenericAPIView` with read/write/list serializer hooks | Every API view |
| `viewsets.py` | `GenericViewSet`, `ReadOnlyModelViewSet`, `ModelViewSet` | Every viewset |
| `mixins.py` | Service method discovery mixins | Automatic via viewsets |
| `serializers.py` | `FileUploadSerializer`, `UserAuditRetrieveSerializer` | File uploads, audit display |
| `pagination.py` | `StandardLimitOffsetPagination` | All paginated endpoints |
| `renderers.py` | `StandardJSONRenderer` | Wraps JSON in `{data, meta, message, code}` |
| `exception_handler.py` | `custom_exception_handler` | Maps errors to the same envelope |
| `exceptions.py` | `HTTPException`, `NotFoundException`, `BadRequestException` | All error responses |
| `middleware.py` | `LoggingMiddleware` (request ID) | Applied globally |
| `logging.py` | structlog `get_logger`, `set_request_context` | All logging |
| `db/models.py` | `TimestampsMixin`, `UserAuditMixin` | All models |
| `db/fields.py` | `EncryptedCharField`, `EncryptedTextField`, etc. | Sensitive data |
| `db/utils.py` | `db_retry`, `db_can_connect` | Resilient DB operations |
| `llm/` | `LLMFactory`, `LLMProvider` (LiteLLM) | All LLM calls |
| `memory/` | `MemoryStore` protocol, `Mem0Store`, `InMemoryStore` | Agent memory |
| `conversation/` | `StateGraph` builder, checkpointing | Agent graphs |

## Rules

- Do NOT add app-specific code here — this is shared infrastructure only
- Do NOT import from apps into core (no circular deps)
- New utilities belong here ONLY if they serve 2+ apps
- All changes here affect the entire project — be careful with breaking changes
