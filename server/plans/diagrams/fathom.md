# Fathom integration — diagrams (v1 MVP)

Visualizations of the Fathom integration as designed in [05-integration-architecture.md](../05-integration-architecture.md) and [06-deployment-and-self-hosting.md](../06-deployment-and-self-hosting.md). Use markdown preview (VS Code: <kbd>⌘⇧V</kbd>) to render the Mermaid diagrams.

**v1 MVP scope** (locked):
- 4 files per simple provider (`provider.py`, `client.py`, `adapter.py`, `tasks.py`)
- One model in `integrations` app: `DeliveryPackage` (no `WebhookDelivery`, no `IngestionJob`)
- One service: `RegistryService` (no `IngestionService` — view-direct)
- No `BronzeStorage` facade — task calls `default_storage` directly
- No `TokenBucket` — add when first rate limit bites
- Webhook callback: `/api/v1/integrations/{slug}/webhook/callback`
- OAuth callback: `/api/v1/integrations/{slug}/oauth/callback`
- Per-provider Celery tasks live in `providers/<vendor>/<product>/tasks.py`

---

## 1. Class diagram — framework primitives + Fathom implementation

```mermaid
classDiagram
    direction TB

    namespace core_integrations {
        class IntegrationProvider {
            <<Protocol>>
            +slug: str
            +display_name: str
            +oauth_provider_slug: str
            +token_scope: Literal
            +default_authorize_url: str
            +default_token_url: str
            +default_scopes: list~str~
            +supports_webhooks: bool
            +client(token) BaseHTTPClient
            +webhook_handler() BaseWebhookHandler
            +oauth_handler(cfg) BaseOAuthHandler
            +adapter_for(raw) BaseAdapter
        }
        class BaseHTTPClient {
            <<abstract>>
            +token: OAuthToken
            +base_url: str
            +request(method, path, **kw) dict
            +get(path, params) dict
            +post(path, body) dict
            +paginate(path, strategy) Iterator
        }
        class BaseWebhookHandler {
            <<abstract>>
            +config: OAuthProvider
            +verify(payload, signature) bool
            +parse(payload) dict
            +resolve_workspace(parsed)* Workspace
        }
        class BaseOAuthHandler {
            +config: OAuthProvider
            +build_authorize_url(state, redirect_uri) str
            +exchange_code(code) dict
            +parse_token_response(resp) dict
            +refresh(token) OAuthToken
            +revoke(token) None
            +handle_callback(code, state, request) OAuthToken
        }
        class BaseAdapter {
            <<abstract>>
            +raw: dict
            +external_id()* str
            +title()* str
            +occurred_at()* datetime
            +to_text()* str
            +to_markdown()* str
            +to_json()* dict
            +metadata() dict
        }
        class Registry {
            -_REGISTRY: dict
            +register(cls) cls
            +all_loaded() list
            +configured_for_workspace(ws) list
            +get(slug) IntegrationProvider
        }
    }

    namespace providers_fathom {
        class FathomProvider {
            +slug = "fathom"
            +display_name = "Fathom"
            +oauth_provider_slug = "fathom"
            +token_scope = "user"
            +default_authorize_url = "..."
            +default_token_url = "..."
            +default_scopes = ["transcripts:read"]
            +supports_webhooks = True
            +client(token) FathomClient
            +webhook_handler() BaseWebhookHandler*
            +oauth_handler(cfg) BaseOAuthHandler*
            +adapter_for(raw) FathomMeetingAdapter
        }
        class FathomClient {
            +base_url = "https://api.fathom.video/external/v1"
            +get_meeting(id) dict
            +get_transcript(id) dict
        }
        class FathomMeetingAdapter {
            +external_id() str
            +title() str
            +occurred_at() datetime
            +to_json() dict
            +metadata() dict
        }
        class ingest_fathom_meeting {
            <<Celery task>>
            +ingest_fathom_meeting(workspace_id, meeting_id)
        }
    }

    namespace integrations_app {
        class RegistryService {
            +current_user: User
            +company: Workspace
            +list_for_workspace(ws) list
            +get_status(ws, slug) IntegrationStatus
            +initiate_connect(ws, user, slug) AuthorizeURL
            +disconnect(ws, user, slug) None
            +handle_callback(slug, code, state, request) OAuthToken
        }
    }

    IntegrationProvider <|.. FathomProvider : implements
    BaseHTTPClient <|-- FathomClient
    BaseAdapter <|-- FathomMeetingAdapter

    FathomProvider --> FathomClient : creates
    FathomProvider --> FathomMeetingAdapter : creates per-raw
    FathomProvider ..> BaseWebhookHandler : uses default*
    FathomProvider ..> BaseOAuthHandler : uses default*

    Registry o-- IntegrationProvider : holds slugs→classes
    RegistryService --> Registry : lookup
    RegistryService --> BaseOAuthHandler : initiate + callback

    ingest_fathom_meeting --> Registry : get("fathom")
    ingest_fathom_meeting --> FathomClient : get_meeting / get_transcript
    ingest_fathom_meeting --> FathomMeetingAdapter : title / metadata / to_json
```

\* Fathom uses framework defaults for webhook + OAuth; only Provider, Client, Adapter, Tasks are Fathom-specific files (4 total).

---

## 2. Class diagram — data models (one new model)

```mermaid
classDiagram
    direction LR

    namespace authentication_app {
        class OAuthProvider {
            +id: UUID
            +slug: str  ~unique~
            +display_name: str
            +is_enabled: bool
            +client_id: str
            +client_secret: EncryptedStr
            +redirect_uri: URL
            +default_scopes: JSON
            +authorize_url: URL
            +token_url: URL
            +webhook_secret: EncryptedStr
            +metadata: JSON
        }
        class OAuthToken {
            +id: UUID
            +provider: FK OAuthProvider
            +user: FK User ~nullable~
            +workspace: FK Workspace ~nullable~
            +granter: FK User
            +access_token: EncryptedStr
            +refresh_token: EncryptedStr
            +expires_at: datetime
            +scope: str
        }
    }

    namespace integrations_app_models {
        class DeliveryPackage {
            +id: UUID
            +workspace: FK Workspace
            +provider: str  "fathom"
            +provider_item_id: str  Fathom meeting id
            +provider_item_type: str  "meeting"
            +title: str  adapter.title
            +occurred_at: datetime  adapter.occurred_at
            +storage_key: str  default_storage key
            +metadata: JSON  adapter.metadata
            ~UniqueConstraint(workspace, provider, provider_item_id)~
        }
    }

    namespace chat_app_models {
        class Workspace
        class User
    }

    namespace storage {
        class default_storage {
            <<Django STORAGES default >>
            +save(key, content)
            +open(key) file
            +url(key) str
        }
    }

    OAuthToken --> OAuthProvider : FK
    OAuthToken --> User : FK ~nullable~
    OAuthToken --> Workspace : FK ~nullable~

    DeliveryPackage --> Workspace : FK
    DeliveryPackage ..> default_storage : storage_key points at
```

**Deferred from v1** (revive when needed): `WebhookDelivery`, `IngestionJob`, `BronzeStorage` framework primitive, `WorkspaceStorageConfig`. See [02-data-model.md#open](../02-data-model.md#open).

---

## 3. Sequence — webhook ingestion flow

```mermaid
sequenceDiagram
    autonumber
    actor Fathom as Fathom service
    participant View as ProviderWebhookView<br/>POST /api/v1/integrations/fathom/webhook/callback
    participant Reg as Registry
    participant FP as FathomProvider
    participant WH as BaseWebhookHandler<br/>(default)
    participant Q as Celery / Redis
    participant Task as providers/fathom/tasks.py<br/>ingest_fathom_meeting
    participant FC as FathomClient
    participant FA as FathomMeetingAdapter
    participant DB as Postgres
    participant Storage as default_storage<br/>(STORAGES["default"])

    Fathom->>+View: POST webhook<br/>headers+payload
    View->>Reg: get("fathom")
    Reg-->>View: FathomProvider
    View->>FP: webhook_handler()
    FP-->>View: BaseWebhookHandler (default)
    View->>+WH: verify(payload, sig)
    WH-->>-View: ok (401 if invalid)
    View->>+WH: parse(payload)
    WH-->>-View: parsed
    View->>+WH: resolve_workspace(parsed)
    Note over WH,DB: looks up OAuthToken via<br/>Fathom-side identifier in payload
    WH->>DB: OAuthToken lookup
    DB-->>WH: token
    WH-->>-View: workspace
    View->>Q: ingest_fathom_meeting.delay(ws.id, parsed["meeting_id"])
    View-->>-Fathom: 200 OK (fast)

    Q->>+Task: ingest_fathom_meeting(workspace_id, meeting_id)
    Task->>DB: OAuthToken.objects.get(provider=fathom, workspace_id)
    Task->>Reg: get("fathom")
    Reg-->>Task: FathomProvider
    Task->>FP: client(token)
    FP-->>Task: FathomClient
    Task->>+FC: get_meeting(meeting_id)
    FC-->>-Task: meeting (dict)
    Task->>+FC: get_transcript(meeting_id)
    FC-->>-Task: transcript (dict)
    Task->>FP: adapter_for(raw)
    FP-->>Task: FathomMeetingAdapter
    Task->>+FA: title() / occurred_at() / external_id() / metadata() / to_json()
    FA-->>-Task: values
    Task->>Storage: save("{ws_id}/fathom/meetings/{meeting_id}.json",<br/>ContentFile(json.dumps(adapter.to_json())))
    Task->>DB: DeliveryPackage.update_or_create<br/>UniqueConstraint(ws, "fathom", meeting_id)
    Task-->>-Q: done
```

---

## 4. Sequence — OAuth connect flow

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Client as Web/API client
    participant View as IntegrationViewSet<br/>POST /api/v1/integrations/fathom/connect
    participant RS as RegistryService
    participant Reg as Registry
    participant FP as FathomProvider
    participant OH as BaseOAuthHandler<br/>(default)
    participant DB as Postgres
    actor Fathom as Fathom OAuth server
    participant CB as ProviderOAuthCallbackView<br/>GET /api/v1/integrations/fathom/oauth/callback

    User->>+Client: click "Connect Fathom"
    Client->>+View: POST /connect<br/>X-Workspace-Id
    View->>RS: initiate_connect(ws, user, "fathom")
    RS->>DB: OAuthProvider.objects.get(slug="fathom")
    alt OAuthProvider.is_enabled = False
        RS-->>View: raise NotConfigured
        View-->>Client: 503 not configured
    else enabled
        RS->>Reg: get("fathom")
        Reg-->>RS: FathomProvider
        RS->>FP: oauth_handler(cfg)
        FP-->>RS: BaseOAuthHandler (default)
        RS->>+OH: build_authorize_url(state, redirect_uri)
        OH-->>-RS: authorize_url<br/>(state encodes user_id, ws_id, slug, redirect_to)
        RS-->>-View: AuthorizeURL
        View-->>-Client: 200 {authorize_url}
        Client->>User: redirect to authorize_url
    end

    User->>+Fathom: authorize app + scopes
    Fathom-->>-User: redirect back with ?code&state

    User->>+CB: GET /api/v1/integrations/fathom/oauth/callback?code&state
    CB->>RS: handle_callback("fathom", code, state, request)
    RS->>Reg: get("fathom")
    Reg-->>RS: FathomProvider
    RS->>FP: oauth_handler(cfg)
    FP-->>RS: BaseOAuthHandler
    RS->>+OH: handle_callback(code, state, request)
    OH->>OH: verify signed state → recover (user, ws)
    OH->>+Fathom: POST token_url<br/>{code, client_id, client_secret}
    Fathom-->>-OH: {access_token, refresh_token, expires_in, scope}
    OH->>OH: parse_token_response(resp)
    OH->>DB: OAuthToken.create<br/>provider=fathom, user=u<br/>access=encrypted, refresh=encrypted
    OH-->>-RS: OAuthToken
    RS-->>CB: success
    CB-->>-User: 302 redirect → /app/integrations/fathom?status=connected
```

---

## 5. Sequence — OAuth disconnect flow

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Client as Web/API client
    participant View as IntegrationViewSet<br/>POST /api/v1/integrations/fathom/disconnect
    participant RS as RegistryService
    participant Reg as Registry
    participant FP as FathomProvider
    participant OH as BaseOAuthHandler<br/>(default)
    participant DB as Postgres
    actor Fathom as Fathom OAuth server

    User->>+Client: click "Disconnect Fathom"
    Client->>+View: POST /disconnect<br/>X-Workspace-Id
    View->>RS: disconnect(ws, user, "fathom")
    RS->>DB: OAuthToken.objects.get(provider__slug="fathom", user=user)
    alt no token
        RS-->>View: 404 not connected
        View-->>Client: 404
    else
        RS->>Reg: get("fathom")
        Reg-->>RS: FathomProvider
        RS->>FP: oauth_handler(cfg)
        FP-->>RS: BaseOAuthHandler
        RS->>+OH: revoke(token)
        OH->>+Fathom: POST revocation endpoint<br/>(best-effort)
        Fathom-->>-OH: 200 / error (ignored)
        OH-->>-RS: ok
        RS->>DB: token.delete()
        RS-->>-View: ok
        View-->>-Client: 204
    end
```

---

## 6. Component diagram — module wiring (v1)

```mermaid
graph TB
    subgraph "donna/core/integrations/<br/>(framework, no app-model deps)"
        IP[IntegrationProvider<br/>Protocol]
        BHC[BaseHTTPClient]
        BWH[BaseWebhookHandler]
        BOH[BaseOAuthHandler]
        BA[BaseAdapter]
        REG[Registry<br/>+ @register]
    end

    subgraph "providers/fathom/<br/>(4 files)"
        FP[FathomProvider<br/>provider.py]
        FCl[FathomClient<br/>client.py]
        FA[FathomMeetingAdapter<br/>adapter.py]
        FT[ingest_fathom_meeting<br/>tasks.py]
    end

    subgraph "donna/integrations/<br/>(Django app)"
        DP[DeliveryPackage<br/>models.py]
        RS[RegistryService<br/>services.py]
        Views[API Views:<br/>IntegrationViewSet<br/>ProviderWebhookView<br/>ProviderOAuthCallbackView]
        TasksAgg[tasks.py<br/>thin pointer]
        Apps[apps.py<br/>recursive discovery —<br/>imports provider.py + tasks.py]
        Cmd[Mgmt cmds:<br/>integrations_bootstrap]
    end

    subgraph "donna/authentication/<br/>(OAuth lifecycle)"
        OP[OAuthProvider model]
        OT[OAuthToken model]
    end

    subgraph "Django STORAGES['default']<br/>(env-var driven)"
        S3[S3-compatible<br/>AWS / SeaweedFS / R2 / ...]
        FSb[Filesystem]
        GCS[GCS / Azure]
    end

    subgraph "Outside Donna"
        Fathom_API[Fathom API]
        Fathom_WH[Fathom webhook]
        Browser[User browser]
    end

    FP -.implements.-> IP
    FCl -.extends.-> BHC
    FA -.extends.-> BA
    FP -. uses default .-> BWH
    FP -. uses default .-> BOH

    Apps --> REG
    Apps --> FP
    Apps --> FT

    Browser --> Views
    Fathom_WH --> Views
    Views --> RS
    Views --> BWH
    RS --> REG
    RS --> BOH
    RS --> OP
    RS --> OT

    FT --> REG
    FT --> OT
    FT --> FP
    FP --> FCl
    FP --> FA
    FCl --> Fathom_API
    FT --> DP
    FT --> S3
    FT --> FSb
    FT --> GCS

    BOH --> OP
    BOH --> OT

    Apps --> Cmd
    Cmd --> OP
```

---

## 7. Endpoint surface (6 endpoints, v1)

| # | Method | Path | Tenant via | Auth | View | Returns |
|---|---|---|---|---|---|---|
| 1 | `GET` | `/api/v1/integrations` | Header | User | `IntegrationViewSet.list` | List of providers + status |
| 2 | `GET` | `/api/v1/integrations/{slug}` | Header | User | `IntegrationViewSet.retrieve` | One provider detail |
| 3 | `POST` | `/api/v1/integrations/{slug}/connect` | Header | User | `IntegrationViewSet.connect` | `{authorize_url}` |
| 4 | `POST` | `/api/v1/integrations/{slug}/disconnect` | Header | User | `IntegrationViewSet.disconnect` | 204 |
| 5 | `POST` | `/api/v1/integrations/{slug}/webhook/callback` | — | Signature | `ProviderWebhookView.post` | 200 (fast) |
| 6 | `GET` | `/api/v1/integrations/{slug}/oauth/callback` | — | State param | `ProviderOAuthCallbackView.get` | 302 redirect |

Endpoints 5 + 6 are non-tenanted and added to `WorkspaceMiddleware.IGNORED_PATHS` via URL-suffix matching (`endswith("/webhook/callback")` and `endswith("/oauth/callback")`).
