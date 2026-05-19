# Data model

All models live in their app's `models.py` per the standard layout. Primary keys are UUIDs throughout (opaque IDs matter in a multi-tenant product). Every model uses `TimestampsMixin`; entities owned by a user also use `UserAuditMixin`. Both mixins are in `donna.core.db.models`.

## Model inventory

| # | Model | App | Scope | Mixins |
|---|---|---|---|---|
| 1 | `User` | users | Global (email-unique) | (extends `AbstractUser`) |
| 2 | `Workspace` | workspaces | Tenant root | Timestamps + UserAudit |
| 3 | `WorkspaceMembership` | workspaces | Join: User × Workspace | Timestamps |
| 4 | `Channel` | chat | Belongs to Workspace | Timestamps + UserAudit |
| 5 | `ChannelMembership` | chat | Join: User × Channel | Timestamps |
| 6 | `AgentSession` | chat | N:1 with Channel | Timestamps |
| 7 | `Message` | chat | Belongs to Channel | Timestamps |
| 8 | `Document` | chat | Belongs to Channel | Timestamps + UserAudit |
| 9 | `OAuthProvider` | authentication | Per deployment | Timestamps + UserAudit |
| 10 | `OAuthToken` | authentication | Per Provider × (User XOR Workspace) | Timestamps |
| 11 | `DeliveryPackage` | integrations | Per Workspace × Provider × item (ingested record) | Timestamps |

`OAuthProvider`/`OAuthToken` carry the deployment-config layer for integrations — see [05-integration-architecture.md#deployment-model](05-integration-architecture.md#deployment-model). `DeliveryPackage` (model 11) lives in the `integrations` app and is detailed in [05-integration-architecture.md#core-models](05-integration-architecture.md#core-models). v1 is intentionally minimal: no `WebhookDelivery` (idempotency moves to `DeliveryPackage`'s `UniqueConstraint`), no `IngestionJob` (no backfill yet), no bronze storage layer (the Celery task writes the raw payload directly via `default_storage`).

---

## 1. User

Global identity, keyed by email. A user is the same entity across every workspace they're a member of — no per-tenant duplication.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `email` | EmailField, unique | The login identifier (`USERNAME_FIELD = "email"`) |
| `full_name` | CharField | Required by `core/serializers.py:UserAuditRetrieveSerializer` |
| `username` | — | Removed (`= None`) |

Uses a custom `UserManager` so `create_user`/`create_superuser` accept `email` instead of `username`. Settings must declare `AUTH_USER_MODEL = "users.User"` before any migrations run.

## 2. Workspace

The tenant root. Anyone authenticated can create one; the creator's `WorkspaceMembership` is seeded with role=OWNER inside the same transaction.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | CharField(255) | Display name |
| `slug` | SlugField(80), unique globally | Used in URLs/admin; auto-generated from name if not provided |
| `members` | M2M User (through WorkspaceMembership) | |

The slug is **globally unique**, not just unique-per-anything-else (workspaces are top-level tenants — they have nothing to be unique-within). The service handles auto-generation with a numeric suffix on collision.

## 3. WorkspaceMembership

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `workspace` | FK Workspace, on_delete=CASCADE | |
| `user` | FK User, on_delete=CASCADE | |
| `role` | CharField, choices=Role | OWNER / ADMIN / MEMBER / GUEST |
| `UniqueConstraint("workspace", "user")` | | One membership per pair |

**Role semantics:**
- `OWNER` — full control, including delete-workspace. Exactly one expected (service enforces).
- `ADMIN` — manage members, channels, settings. Cannot delete the workspace.
- `MEMBER` — default; can chat, create channels.
- `GUEST` — reserved, not used yet; future use for external collaborators (Slack-Connect-style).

Ownership transfer is `PATCH /members/{user_id}` with `role=OWNER` — the service atomically demotes the existing OWNER to ADMIN.

## 4. Channel

A room inside a workspace. Carries the `kind` discriminator so DMs can reuse all channel machinery.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `workspace` | FK Workspace, CASCADE | |
| `kind` | CharField, choices={CHANNEL, DIRECT} | DMs are DIRECT |
| `name` | CharField(120), blank=True | DMs have no name |
| `slug` | SlugField(120), blank=True | DMs have no slug |
| `topic` | CharField(255), blank | |
| `visibility` | CharField, choices={PUBLIC, PRIVATE} | DMs are always PRIVATE |
| `members` | M2M User (through ChannelMembership) | |

**Constraints:**
- `UniqueConstraint("workspace", "slug") WHERE slug != ''` — slug uniqueness applies only to named channels; DMs are exempt.
- `CheckConstraint dm_must_be_private` — `~Q(kind=DIRECT) | Q(visibility=PRIVATE)`. Enforces the "DMs cannot be public" rule at the database level rather than relying on services to remember.

**Index** on `(workspace, kind)` — listing "regular channels in this workspace" vs "DMs for this workspace" is a frequent query.

**Why `kind` instead of a separate `DirectMessage` model:** a separate model would force `Message` to have a polymorphic parent (channel OR DM), duplicate membership/agent infrastructure, and add a second URL surface. Discriminating with `kind` reuses everything; the cost is two fields (`name`, `slug`) that DMs leave blank.

## 5. ChannelMembership

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `channel` | FK Channel, CASCADE | |
| `user` | FK User, CASCADE | |
| `role` | CharField, choices={ADMIN, MEMBER} | |
| `UniqueConstraint("channel", "user")` | | |

Channel admins are needed for managing private-channel membership and editing channel settings; the creator becomes ADMIN automatically.

## 6. AgentSession

The agent's persistent state in a channel. **N:1 with Channel** — typically one per channel today, but the schema admits multiple personas/specialists without restructuring.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `channel` | FK Channel, CASCADE | Workspace is reachable via `channel.workspace` |
| `name` | CharField(120), default="Donna" | Multiple agents would have different names |
| `memory` | JSONField, default={} | Distilled long-term memory |
| `config` | JSONField, default={} | Per-channel model/tools/prompt overrides |
| `last_active_at` | DateTimeField, nullable | |

**Why not fields on Channel:** independent lifecycle (memory reset = delete + recreate the session), polymorphic target for `Message.author_agent`, future multi-persona support. The 1:1 collapse is a tempting refactor that we resist.

**Why not store conversation history here:** history is just `Message` rows where `author_agent` points to this session. Filtering by an indexed FK is faster than maintaining a parallel field.

## 7. Message

A message in a channel, authored by exactly one of: a User or an AgentSession.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `channel` | FK Channel, CASCADE | |
| `author_user` | FK User, SET_NULL, nullable | User author |
| `author_agent` | FK AgentSession, SET_NULL, nullable | Agent author |
| `body` | TextField | |

**Constraints:**
- `CheckConstraint message_has_exactly_one_author` — `Q(author_user__isnull=False, author_agent__isnull=True) | Q(author_user__isnull=True, author_agent__isnull=False)`. Exactly one author column is set.
- Index on `(channel, created_at)` — the message scroll for a channel.

**Polymorphism choice — rejected alternatives:**
- **ContentType / generic FK** — overkill; we have only two author types, ever. Generic FKs invite N+1 queries and lose joinability.
- **`Actor` abstraction (single FK to a model whose rows are users or agents)** — adds a junction table and a layer of indirection for no real flexibility gain at this size.
- **Sentinel User row for "the agent"** — would lose per-channel agent identity; can't query "all messages from this channel's agent" cleanly.

Two nullable FKs + a CHECK constraint is the cleanest minimal pragmatic choice.

## 8. Document

A Cowork-style collaborative artifact created within a channel.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `channel` | FK Channel, CASCADE | |
| `title` | CharField(255) | |
| `body` | TextField, blank | |

**v1 semantics:** last-write-wins on full-body PATCH. Real collaborative editing (OT/CRDT) is a separate effort, intentionally deferred.

## 9. OAuthProvider

**Per-deployment configuration row** for an OAuth-capable external service (Fathom, Gmail, Slack, etc.). One row per provider per deployment. The deployment owner (Donna team for Cloud, customer sysadmin for on-premise) populates this with their own OAuth app credentials. Until `is_enabled=True` and credentials are set, the provider doesn't appear to users.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `slug` | CharField(64), unique | Matches provider module slug (`"fathom"`). Join key between code and config. |
| `display_name` | CharField(120) | "Fathom" |
| `is_enabled` | BooleanField, default=False | Master switch — false until admin configures. |
| `client_id` | CharField(255), blank | Deployer's OAuth app client ID |
| `client_secret` | EncryptedCharField, blank | Deployer's OAuth app secret |
| `redirect_uri` | URLField, blank | This deployment's callback URL |
| `default_scopes` | JSONField, default=list | Scopes to request when user connects |
| `authorize_url` | URLField | Provider's OAuth authorize endpoint |
| `token_url` | URLField | Provider's OAuth token endpoint |
| `webhook_secret` | EncryptedCharField, blank | For webhook signature verification |
| `metadata` | JSONField, default=dict | Provider-specific extras (e.g., Slack signing secret, region overrides) |
| | | TimestampsMixin + UserAuditMixin |

`authorize_url`/`token_url`/`default_scopes` are seeded from the provider class's `default_*` attributes by the `integrations_bootstrap` management command on first boot. Admin only enters `client_id`/`client_secret`/`redirect_uri` and flips `is_enabled`.

**Why per-deployment, not global:** the redirect URI for an on-premise install is `https://donna.acme.internal/...`, not Donna Cloud's URL. Each deployment must register its own OAuth app with the upstream provider (industry-standard BYO OAuth flow). See [06-deployment-and-self-hosting.md](06-deployment-and-self-hosting.md) for the customer-facing flow.

**Per-vendor, not per-integration.** When the same upstream vendor ships multiple products that share OAuth — Google (Gmail + Drive + Calendar), Microsoft (Outlook + Teams + OneDrive), Atlassian (Jira + Confluence) — there is **one `OAuthProvider` row per vendor**, not per product. Provider classes in `integrations/providers/<vendor>/<product>/` set `oauth_provider_slug` to the vendor slug (e.g., `"google"`) and share the row. The `integrations_bootstrap` command groups provider classes by `oauth_provider_slug` and unions their `default_scopes` into the single row. See [05-integration-architecture.md#deployment-model](05-integration-architecture.md#deployment-model) for the layout rule (flat for single-product vendors, nested for multi-product) and the bootstrap implementation.

## 10. OAuthToken

The actual credential. Per provider × (User XOR Workspace).

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `provider` | FK OAuthProvider, CASCADE | |
| `user` | FK User, CASCADE, nullable | Set for user-scoped tokens |
| `workspace` | FK Workspace, CASCADE, nullable | Set for workspace-scoped tokens |
| `granter` | FK User, SET_NULL, nullable | Who authorized (audit). For workspace tokens. |
| `access_token` | EncryptedCharField | |
| `refresh_token` | EncryptedCharField, blank | |
| `expires_at` | DateTimeField, nullable | |
| `scope` | CharField, blank | Actual scopes granted |
| | | TimestampsMixin |

**Constraint:** `CheckConstraint token_has_exactly_one_owner` — `Q(user__isnull=False, workspace__isnull=True) | Q(user__isnull=True, workspace__isnull=False)`.

**Token scope semantics:**
- **User-scoped** — personal use; only the granter can read with it. Used by per-user sources (a user's Gmail, a user's Linear).
- **Workspace-scoped** — granted by a user, usable by all members of that workspace. Records the `granter` for audit. Used by shared sources (workspace's Slack, workspace's HubSpot).

Token rotation, expiry, and refresh logic live with this model. Use `EncryptedCharField` from `core/db/fields.py` for `access_token`/`refresh_token` — sensitive in-DB content.

---

## Cross-cutting choices

- **UUID primary keys everywhere.** Opaque IDs prevent enumeration; multi-tenant requires this.
- **`TimestampsMixin` + `UserAuditMixin` from `core/db/models.py`** — applied where each makes sense. Join tables get Timestamps only (audit on join rows is noise).
- **`db_table` explicit on every model** — readable in DB tools, doesn't drift if the app is renamed.
- **`on_delete=CASCADE` on most FKs**, `SET_NULL` on `Message.author_*` so messages survive a deleted user.
- **Encryption (`core/db/fields.py:Encrypted*Field`)** — available but not used in models above. Use for OAuthToken's access/refresh tokens (the only sensitive in-DB content so far).

## Rejected models / dropped concepts

- **`KnowledgeItem`** (proposed for distilled ingested content) — dropped during initial model design as premature. The landing strategy was open until [05-integration-architecture.md](05-integration-architecture.md) earned the table through the 100+ integration scoping. Lives as `DeliveryPackage` in the `integrations` app — minimal v1 form (6 fields + UniqueConstraint) with concrete fields. (Earlier iterations called it `IngestedItem`; renamed to capture both "delivered to us" and "package of data".)
- **`Integration`** (as a connected-source model) — replaced by `OAuthToken`. The "connection" IS the token.
- **Separate `DirectMessage` model** — collapsed into `Channel.kind=DIRECT`.
- **Plugin-loaded providers (one Django app per provider)** — rejected for v1 in favor of the n8n model: ship-all-as-code in one `integrations` app, opt-out via env, no runtime plugin loading. See [05-integration-architecture.md#deployment-model](05-integration-architecture.md#deployment-model).

## Open

- **DM dedup** — currently a service-level concern (`get_or_create_dm(workspace, users)` under a transaction). If race conditions bite, add a derived `member_set_hash` column with a unique constraint.
- **Threads on Message** — deferred; would be a self-FK or a separate `MessageThread` model.
- **Reactions, attachments, read receipts** — deferred; well-understood patterns when needed.
- **`DeliveryPackage` extension fields** — `participants`, `thread_id`, `summary`, etc. land when cross-provider queries actually need them, not before.
- **`WorkspaceStorageConfig`** — deferred to v2+. Per-workspace storage backend override (point a workspace at its own bucket / credentials / filesystem path) for data-residency / enterprise compliance. The per-deployment global `STORAGES["default"]` covers v1. See [06-deployment-and-self-hosting.md](06-deployment-and-self-hosting.md).
- **`WebhookDelivery`** — deferred. v1 collapses webhook idempotency into `DeliveryPackage`'s `UniqueConstraint(workspace, provider, provider_item_id)` because re-fetching from the upstream API on a duplicate webhook is harmless (just an extra API call; the row upserts). Returns if/when we need a discrete audit trail of webhook receipts independent of the resulting package.
- **`IngestionJob`** — deferred until backfill / scheduled ingestion lands. v1 uses the Celery task directly with arguments (`workspace_id`, `item_id`) — no row tracking the run.
- **Bronze storage primitive (`BronzeStorage`)** — deferred. The v1 Fathom task uses Django's `default_storage` directly. A facade returns if/when (a) multiple providers duplicate storage boilerplate or (b) we need bronze-specific features (presigned URLs, lifecycle policies, replay).
