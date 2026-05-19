# Reference: integration platform landscape and design patterns

**This is reference material, not a plan.** It captures the *what other products do and why*, gathered from research during the Donna integration architecture sessions. Read it to understand the landscape, the patterns, and the design vocabulary; refer back to it when re-evaluating Donna's choices.

Decisions Donna locks in based on this material live in [05-integration-architecture.md](05-integration-architecture.md) and [06-deployment-and-self-hosting.md](06-deployment-and-self-hosting.md). This doc explains the *background reasoning*.

---

## Table of contents

1. [The integration platform landscape](#1-the-integration-platform-landscape)
2. [Build vs buy economics](#2-build-vs-buy-economics)
3. [How OSS platforms hold hundreds of integrations](#3-how-oss-platforms-hold-hundreds-of-integrations)
4. [The MCP shift — AI-native integration](#4-the-mcp-shift--ai-native-integration)
5. [Workflow engines for ingestion](#5-workflow-engines-for-ingestion)
6. [The n8n deployment model](#6-the-n8n-deployment-model)
7. [Self-hosting infrastructure patterns](#7-self-hosting-infrastructure-patterns)
8. [OSS licenses for commercial integration products](#8-oss-licenses-for-commercial-integration-products)
9. [Webhook reliability infrastructure](#9-webhook-reliability-infrastructure)
10. [Decision framework: which path for your product](#10-decision-framework-which-path-for-your-product)
11. [Sources](#sources)

---

## 1. The integration platform landscape

The integration tooling space splits into four distinct categories. Pick the wrong category and you spend a year fighting the platform.

| Category | What it does | Examples | Use when |
|---|---|---|---|
| **Unified API (data sync)** | Pulls data from many SaaS sources, normalizes to common schemas, caches in their store | Merge.dev, Finch, Apideck | You need HRIS/ATS/CRM data normalized; speed beats depth; one-way read |
| **Code-first integration framework** | TypeScript/Python framework, OSS, hundreds of pre-built syncs + custom code allowed | **Nango**, **Membrane**, dlt | Integrations are core product; want control + breadth; comfortable owning code |
| **AI-agent action layer** | LLM function calling over hundreds of tools, MCP-native, OAuth-managed | **Composio**, **Arcade**, Paragon ActionKit | Agent needs to *act* in third-party tools (post, create, send); not just read |
| **Embedded iPaaS** | Visual workflow builder, end-user-facing | Paragon, Alloy, Workato Embedded | Your end users build their own automations; integration is your customer's job, not yours |

### The key categorical question

**"Does my agent only read data, or does it also need to act?"**

- **Read only** → Unified API or code-first sync (Merge, Nango, Airbyte)
- **Act in tools (post message, create issue, send email)** → Agent action layer (Composio, Arcade)
- **Both** → Probably code-first framework with agent layer on top

This is why Donna landed on a 90/10 mix: custom code for Tier 1 (deep, reads + acts), agent action layer for Tier 2 (many actions, few reads), optional sync platform for Tier 3 (reads only, long tail).

### The major players in detail

**Merge.dev** — The unified API leader for HRIS/ATS/CRM. ~200 integrations across 7 categories. Their model: periodically syncs third-party data into their own cache, you read from their normalized schemas. Strengths: speed of deployment, normalized schemas. Weaknesses: data is up to ~2 hours stale (bad for AI use cases), rigid schemas don't fit custom needs. Cost: ~$38k/month at 200 customers — punishing at scale.

**Nango** — Open-source code-first framework. ~400 integrations. You write TypeScript syncs using their SDK; framework handles OAuth, refresh, retries, state. Self-hostable. Best fit for "integrations are core product, we want control."

**Composio** — AI-agent-native action layer. ~500 tools exposed via MCP, 18k+ GitHub stars, MIT license. Built specifically for LLM function calling — agents discover tools dynamically, OAuth handled centrally, MCP runtime included. New category that didn't exist 2 years ago.

**Arcade** — MCP runtime focused on secure authentication and authorization for AI agents. Smaller than Composio but more security-focused.

**Airbyte** — OSS data ELT. ~300 connectors as Docker images. Has a Low-Code YAML CDK (declarative connectors) and a Python CDK (procedural). Self-hostable on Kubernetes. Heavy for one source, pays off at many.

**n8n** — Workflow automation, the Zapier alternative. 400+ integrations as "nodes," 50k+ GitHub stars. Sustainable Use License (fair-code, not OSI-OSS). Has cloud + self-host with the same image.

**Activepieces** — n8n alternative, MIT-licensed, fastest-growing. 200+ pieces (594 if counting AI-agent tools). Cleaner architecture for new products.

**Trigger.dev** — Workflow engine + integrations, Apache 2.0. V3 is self-hostable. More of a workflow primitive than a connector library.

**Membrane** — Code-first, AI-agent focused, smaller catalog. MIT.

**Pipedream** — 2000+ integrations, cloud-first, partial OSS. Heaviest catalog but cloud-only for the full feature set.

**Inngest** — Durable workflow engine. Apache 2.0 for dev server; cloud is primary offering. Strong observability. Best for "we need reliable async workflows" rather than "we need many SaaS connectors."

**Singer** — Open spec (not a product) for ELT taps and targets. Foundation for Stitch and Meltano. Less common in 2026.

---

## 2. Build vs buy economics

The "build it ourselves" instinct is right at small scale and catastrophic at large scale. Concrete numbers from the research:

### Cost breakdown

- **Initial development is 30–40% of TCO.** Maintenance is 60–70%. (Multi-case studies put dev at 21% of 5-year costs.)
- **Per-integration custom cost** at maturity: $50k–$150k/year. This includes maintenance, vendor API changes, QA.
- **3-platform comparison**: DIY = $20k–$32k Year 1. Unified API = $1.6k–$5.6k Year 1. Gap widens with maintenance.
- **The 150-scripts problem**: 30 integrations × 5 object types = 150 scripts to maintain. Providers deprecate endpoints, change pagination, alter rate limits — every change is a rewrite/test/deploy across the affected scripts.

### Inflection points

| Scale | Path |
|---|---|
| **<5 integrations, simple** | Build it yourself. Frameworks are overkill. |
| **5–10 integrations** | Build it yourself with a framework abstraction. The pain is real but you learn what the framework needs. |
| **10–30 integrations** | Hybrid: deep custom for the strategic ones, platform (Nango/Composio) for the rest. |
| **30–100 integrations** | Mostly platform. Custom only for the 5-10 that *are the product*. |
| **100+ integrations** | Platform-dominant. You don't have an engineering team large enough to maintain 100 custom connectors. |

### Customer-count inflection (from Truto's analysis)

- **<50 customers**: in-house cheaper if you have spare engineering capacity.
- **50–200 customers**: Merge's per-connection economics start to hurt (~$38k/month at 200). Nango's maintenance burden compounds without platform help.
- **>200 customers**: per-connection pricing becomes painful. The decision is now about whether you can absorb the "platform tax" OR the "engineering salary tax."

### Why most teams still build their own (despite the math)

The economics say "buy at scale" but most product teams build. Three reasons make this rational:

1. **Integrations are the product.** For Donna, the agent + ingested context IS the value. Outsourcing the integration layer outsources part of the moat. (Different from "we sell HR software and need Workday data" — there, Merge is correct.)
2. **Custom transform logic.** "Pull transcript and land it" isn't the product. "Transform transcript into agent memory + channel Document + searchable index" is. Platforms don't do that for you; you'd write the transform anyway, just inside their abstraction.
3. **Vendor risk + compliance.** Customer data flowing through a third party is a real concern. Some buyers (especially enterprise) won't tolerate it. SOC2/HIPAA/GDPR multiply the friction.

### The decision framework

**Build when**: integrations are product, you do custom transforms per source, 1-10 providers, compliance pressure, team has bandwidth.

**Buy when**: integrations are infrastructure (not product), pure mirror-the-data-no-transform, 50+ providers, tiny team without ops capacity.

**Hybrid when**: integrations are product but you have a long tail. This is the most common shape for AI products — deep build for the 10 that matter, platform for the 90 that don't.

---

## 3. How OSS platforms hold hundreds of integrations

The engineering trick that makes n8n's 400 nodes, Airbyte's 300 connectors, and Nango's 400 syncs sustainable: **1 framework + N descriptors**, not N implementations.

### The pattern

Most SaaS APIs have the same shape:

| Capability | Variation across 100 providers | What can be shared |
|---|---|---|
| Auth | OAuth2 / Bearer / API key (~5 styles) | OAuth flow, token refresh, header injection |
| Request | REST + JSON (95% of cases) | HTTP client, JSON parsing, error mapping |
| Pagination | Cursor / offset / page (~3 styles) | Iteration with strategy selection |
| Rate limits | Headers-based / per-second / per-day | Token bucket primitive, header parsers |
| Webhooks | HMAC signature in header (~80%) | Generic verifier with key selection |
| Errors | HTTP status + JSON error body | Retry classifier, exception mapping |

**The framework owns the shared 80%. The integration is the unique 20%** — base URL, endpoint paths, field mappings, which pagination strategy to use.

### n8n: declarative `routing` blocks

Each integration is a folder under `packages/nodes-base/nodes/<Name>/`. Most of the file is metadata, not procedural code:

```typescript
export class Pipedrive implements INodeType {
  description: INodeTypeDescription = {
    displayName: 'Pipedrive',
    name: 'pipedrive',
    properties: [
      {
        name: 'operation',
        type: 'options',
        options: [
          { name: 'Create Deal', value: 'createDeal' },
        ],
        routing: {                     // ← THIS is the integration
          request: {
            method: 'POST',
            url: '/deals',
            body: '={{$parameter.fields}}',
          },
        },
      },
    ],
  };
}
```

An entire CRUD integration with no `execute()` method. The framework reads `routing` and runs it. Procedural code only kicks in for the *hard* providers (Slack, Notion, Airtable) — and those are 5–10% of the catalog.

### Airbyte: YAML connectors

Airbyte went further. Many connectors are *literally YAML files*:

```yaml
type: DeclarativeSource
streams:
  - type: DeclarativeStream
    name: customers
    retriever:
      requester:
        url_base: "https://api.example.com"
        path: "/customers"
        authenticator:
          type: OAuth2Authenticator
          token_refresh_endpoint: "https://api.example.com/oauth/token"
        pagination_strategy:
          type: CursorPagination
          cursor_value: "{{ response.next_cursor }}"
    schema_loader:
      type: JsonFileSchemaLoader
      file_path: "./schemas/customers.json"
```

That's a complete connector — auth, pagination, schema, the works. Airbyte calls it the **Low-Code CDK**. Their framework Python reads this YAML and runs it.

They even have an **AI-assisted Connector Builder UI** that generates this YAML from poking around an API.

### Nango: TypeScript SDK

Each Nango integration is a small TypeScript file:

```typescript
import type { NangoSync } from '@nangohq/runner';

export default async function fetchTranscripts(nango: NangoSync) {
  let cursor: string | undefined;
  do {
    const response = await nango.get({
      endpoint: '/transcripts',
      params: cursor ? { cursor } : {},
    });
    await nango.batchSave(response.data.items, 'Transcript');
    cursor = response.data.next_cursor;
  } while (cursor);
}
```

~20 lines for a complete sync. `nango.get` handles auth, refresh, retries, rate limits. `nango.batchSave` handles persistence and idempotency. SDK is the heavyweight; per-provider file is glue.

### Why this scales: the three multipliers

Beyond the framework trick:

1. **Community contributions.** n8n's maintainers didn't write 400 nodes themselves. The CDK pattern *enables* outside contributors — someone needs Pipedrive, writes a 100-line descriptor, opens a PR, maintainers review and merge. This is **the only way to scale past ~30 connectors**.

2. **Plugin / dynamic loading.** n8n loads node folders from disk at startup. Airbyte spins each connector in its own Docker container. Nango imports templates as modules. Adding a connector = adding a file, no core code change.

3. **Provider config as data.** OAuth client IDs, endpoints, scopes → JSON/YAML in a `providers.yaml` file. One generic OAuth flow handles 400 providers, parameterized by the data file.

### The implication

**The real engineering work is the framework, not the integrations.** Once the framework is mature:
- Simple integration: ~100–200 lines (the descriptor)
- Hard integration (Slack, Salesforce, GitHub): 500–1500 lines (procedural code)

This is why I recommend Donna build Fathom *inside the framework* — building it teaches you what the framework needs. By integration #5, the framework is mature and #6-10 are 1-day projects each.

This pattern has a name in classic CS: **declarative configuration + convention over configuration**. Other places it shows up:
- Terraform (declarative cloud resources, providers configure via descriptors)
- Kubernetes (declarative YAML, controllers implement the contract)
- OpenAPI (declarative API spec, codegen produces clients)

The pattern: **describe the shape, share the implementation.**

### Vendor grouping in the codebase

A subtle organizational pattern visible in all three OSS platforms: **multi-product vendors are grouped under a vendor folder; single-product vendors stay flat**. n8n's directory structure makes this explicit:

```
nodes-base/nodes/
├── Aws/{S3, Sqs, Lambda, ...}             ← vendor-grouped
├── Google/{Gmail, Drive, Sheets, ...}     ← vendor-grouped
├── Microsoft/{Outlook, Teams, OneDrive}   ← vendor-grouped
├── Slack/                                  ← single-product, flat
├── Notion/                                 ← single-product, flat
└── Linear/                                 ← single-product, flat
```

Vendor folders typically contain a shared `GenericFunctions.ts` (n8n) or `client.py` (Donna) for common base classes. The OAuth credential is also typically vendor-level — one "Google OAuth2 API" credential serves Gmail + Drive + Sheets in n8n, the same way Donna's `OAuthProvider("google")` serves multiple Google products.

Donna adopted this verbatim — see [05-integration-architecture.md](05-integration-architecture.md#adding-integration-2). The trigger to nest: a second product from the same vendor lands. Don't pre-nest "in case."

---

## 4. The MCP shift — AI-native integration

The single biggest 2026 development in this space. Worth understanding even if you don't adopt MCP immediately.

### What MCP is

**Model Context Protocol** — Anthropic-originated open standard for how LLM agents discover and invoke tools. Industry analysts are calling it *"the REST API moment for AI-enabled SaaS."*

Before MCP, every AI product wrote bespoke wiring: "here's a Slack tool the agent can call, here's a Linear tool, here's a Gmail tool." Each was a custom adapter between the LLM's function-calling interface and the provider's API.

With MCP, providers (or MCP servers) expose tools via a standard protocol. Agents can discover them at runtime, get schemas, and invoke them — without per-provider integration code.

### Why this changes the math for AI products

The bottleneck for AI agents in 2026 isn't "how do we give agents tools?" It's "how do we build integrations fast enough?" MCP collapses that — Composio exposes 500+ tools to your agent via MCP without you writing 500 adapters.

For Donna specifically: the agent needs to act in Slack (post message), Linear (create issue), Gmail (send email), Telegram (DM), etc. Without MCP, this is 100 custom action implementations. With MCP via Composio/Arcade, it's "subscribe to the right tools and the agent has them."

### Who's building on MCP

- **Composio** — MCP-native AI agent toolkit, 500+ tools, MIT, 18k+ GitHub stars
- **Arcade** — MCP runtime focused on secure auth/authz for agents
- **Paragon ActionKit** — single API for real-time actions, AI-command-friendly
- **Anthropic itself** — built MCP into Claude Code and the broader Claude ecosystem

### The categorical shift

Before MCP, the integration platform categories were:
- Unified API (Merge)
- Code-first sync (Nango)
- Embedded iPaaS (Paragon)

After MCP, **a fourth category emerged** that didn't exist 2 years ago: **AI-agent action layer**. This is the right category for AI products that need to *act* in many tools.

For Donna's roadmap, this means: Tier 2 (the agent action layer, ~90 long-tail providers) is solved by Composio or Arcade. Without MCP, Tier 2 would be a 5-person team writing 90 custom action implementations.

---

## 5. Workflow engines for ingestion

The queue-and-worker pattern is universal for ingestion pipelines. The variation is in *which* queue and *which* worker manager.

### The pattern (universal)

```
┌─────────────┐     ┌──────────┐     ┌─────────────┐
│  API server │ →   │  Queue   │  →  │  Worker(s)  │
│  (web tier) │     │  (Redis/ │     │  (long-     │
│             │     │   PG)    │     │   running)  │
└─────────────┘     └──────────┘     └─────────────┘
```

Webhook arrives → API queues a job → returns 200 fast → worker picks up → does the work → marks done. Same shape for backfills and scheduled syncs.

**Why never synchronous**: providers retry on timeout (Fathom, GitHub, Slack, all of them). Synchronous processing means a slow downstream system multiplies into thousands of duplicate retries.

**Why never Lambda**:
- AWS-only — kills the self-host story instantly
- Cold starts make webhook latency unpredictable
- 15-minute Lambda limit doesn't fit long backfills
- Local dev requires LocalStack — extra friction
- Nobody in the integration platform space uses it. There's a reason.

### "Plain workers" — what they are

A **plain worker** is a long-running process that pulls jobs from a queue and runs them. Nothing fancy.

For Donna: a Celery process — `celery -A donna worker --loglevel=info` — inside a Docker container. It:
1. Connects to Redis (queue)
2. Subscribes to task queues
3. Pulls jobs as they arrive
4. Executes them
5. Marks them done/failed
6. Loops forever

That's the whole trick. It's just a Python process in a `while True:` loop, dressed up by Celery.

The deployment shape:

```yaml
services:
  web:
    image: donna/api
    command: gunicorn donna.wsgi
    ports: ["8000:8000"]

  worker:                      # ← "plain worker"
    image: donna/api           # SAME image
    command: celery -A donna worker
    deploy:
      replicas: 4
```

One Docker image. Different start commands. Same dependencies, same models, same everything. **This is the trick that makes "one artifact, two deployment targets" work.**

### The workflow engine options

| | Celery | Django-Q | Inngest | Temporal |
|---|---|---|---|---|
| Maturity | Highest (Django shop standard) | Medium | Newer | High (proven at scale) |
| Required infra | Redis + worker | Postgres only | Inngest server / cloud | Postgres + Cassandra + server |
| Self-host | Excellent | Excellent | Possible, heavier | OSS, full self-host |
| Observability | Manual (Flower) | Built-in admin | Best-in-class | Strong |
| Dev experience | Solid | Simplest | Best | Steep learning curve |
| When to pick | Django default | "Postgres only, no Redis" | Developer velocity > ops cost | Enterprise / massive scale |

**Rule of thumb from the search:**
- Startups: Inngest (operational overhead is the constraint, developer velocity wins)
- Mature companies: Celery (proven, universal)
- Enterprise with platform team: Temporal (control, deep integration, proven scale)
- Pure Postgres shop: Django-Q (no Redis required)

For Donna's stage, **Celery + Redis** is the right pick — Django-shop default, self-host friendly, well-understood. Migration to Inngest or Temporal happens when observability becomes the bottleneck (~integration #10 or load that breaks Celery).

### How the major platforms structure this

- **n8n**: Queue mode separates main (UI + triggers) from worker containers. Redis holds the queue. Self-host can run with 50+ workers managed by Kubernetes.
- **Airbyte**: Temporal under the hood. Each connector runs as a Docker container, orchestrated by Temporal workflows.
- **Nango**: Postgres-backed scheduler + Node.js workers running TypeScript syncs.
- **Inngest** itself: their own durable execution + queueing as a service.

The pattern is universal even when the implementation differs.

---

## 6. The n8n deployment model

Worth its own section because it's the cleanest cloud + self-host story in the space, and it's what Donna adopted.

### The three layers

| Layer | Who decides | What it controls | When set |
|---|---|---|---|
| **1. Shipped** | n8n maintainers (vendor) | Which nodes are in the Docker image | At release |
| **2. Configured** | Self-host sysadmin / Cloud team | Which nodes available + OAuth app credentials | At deploy / admin UI |
| **3. Connected** | End user | Which nodes I have credentials for | At workflow build |

Each layer has a different audience. A node appears to a user only when **all three layers say yes**: code loaded, admin enabled with credentials, user connected.

### Opt-out, not opt-in

All 400 nodes ship in the image. Sysadmin sets `N8N_DISABLED_NODES=foo,bar` to hide what they don't want exposed. This is the opposite of "configure a list of allowed integrations" — and it's better because:

- New nodes appear automatically on upgrade (no settings edit)
- The default is "everything available" — most users want this
- The sysadmin's exception list is short (a few compliance-driven hides)

### BYO OAuth app — the load-bearing piece

The non-negotiable design decision for on-prem: **the customer's sysadmin must register their own OAuth app with each upstream provider** because:
- The redirect URI for on-prem is `https://n8n.customer.internal/...`, not n8n's URL — Slack/Google won't accept the wrong URI.
- Each customer needs their own client_id/secret for audit and compliance.
- Rate limits and approved scopes are per-app.

This is industry-standard for on-prem integration platforms. Nango, Activepieces, Airbyte all require it. The customer onboarding burden is ~10 minutes per Tier 1 provider — accepted as standard cost.

### Same image, cloud and on-prem

n8n's `docker-compose` and Helm chart deploy the *same image*. The only differences:

| | n8n Cloud | n8n Self-host |
|---|---|---|
| Operator | n8n team | Customer sysadmin |
| OAuth app ownership | n8n owns | Customer owns |
| Scale | Auto (within tier) | Manual (add worker replicas) |
| Database | Managed Postgres | Postgres container |
| Updates | Continuous | Customer-driven |

No code branches on deployment mode. All variation is data + configuration.

### Why Donna adopted this verbatim

The model is battle-tested at scale (n8n has tens of thousands of self-host instances). It maps cleanly to Donna's `OAuthProvider` row (Layer 2) + `OAuthToken` row (Layer 3) + provider code (Layer 1). No code branches needed; no special "cloud mode" vs "on-prem mode" handling.

---

## 7. Self-hosting infrastructure patterns

Every successful OSS-with-cloud product uses the same stack. The variation is at the edges; the core is invariant.

### The universal stack

| Layer | OSS-compatible choice | Cloud equivalent |
|---|---|---|
| Object storage | SeaweedFS / Garage (S3 API) | AWS S3 / GCS / R2 |
| Database | Postgres | RDS / Cloud SQL |
| Queue/cache | Redis (or Valkey, the OSS fork) | ElastiCache / Memorystore |
| Workers | Plain containers | ECS / Cloud Run / Kubernetes |
| Secrets | env vars (dev), Vault (prod) | Secrets Manager |
| Deployment | **Helm chart** for prod, Docker Compose for dev | Same Helm chart |

### The S3-compatible story

Everyone codes against the **S3 API**, exposes `S3_ENDPOINT_URL` as config. Then:

- AWS-hosted: real S3 (no endpoint override)
- GCP-hosted: GCS via S3 interop, or native GCS
- Cloudflare: R2 (S3-compatible)
- Self-hosted prod: SeaweedFS or Ceph RGW
- Self-hosted small: Garage (lightweight, Rust)
- Dev: SeaweedFS in Docker

**`boto3`, `s3fs`, `django-storages` all support custom endpoints.** Same code path everywhere.

### MinIO went commercial in 2025

For years, "MinIO" was the default OSS S3-compatible recommendation. In 2025 MinIO pulled features into their paid tier and shifted toward a restrictive license trajectory. They're no longer the OSS default.

Current recommendations:
- **SeaweedFS** — fast, mature, billions-of-files capable. New default.
- **Garage** — lightweight, geo-distributed, Rust-written. Great for small installs.
- **Ceph (RGW)** — enterprise-grade, complex. Only if you already run Ceph.
- **MinIO** — still works for existing deployments, but new ones should default elsewhere.

### Airbyte's lesson — deprecating Docker Compose

In 2024, Airbyte deprecated Docker Compose support in favor of `abctl` (which spins up local Kubernetes). The reasoning:

- Production self-hosters were running on Kubernetes anyway
- Maintaining Docker Compose alongside Helm was duplicate effort
- Kubernetes-only is *consistent* across cloud and on-prem deployments

**Implication for Donna**: Docker Compose is fine for dev environments and small self-hosters; **Helm chart from day one** for production self-host. Don't make Airbyte's mistake of treating Docker Compose as a long-term production deployment story.

### Production infrastructure dependencies (Airbyte's example)

| Component | Cloud (AWS) | Self-host |
|---|---|---|
| Object store | S3 | SeaweedFS / Ceph |
| Database | RDS | Postgres container |
| Secrets | AWS Secrets Manager | Env vars or Vault |
| Logs | CloudWatch | Loki / Promtail |
| Container registry | ECR | Customer's registry or Docker Hub |

Min specs for Airbyte: 4 CPUs, 8GB RAM (2 CPU + 8GB in low-resource mode). Reasonable expectation for "production self-host."

---

## 8. OSS licenses for commercial integration products

This is load-bearing for commercial strategy and most builders ignore it until too late.

### The landscape

| License | OSI-OSS? | Allows commercial SaaS? | Used by |
|---|---|---|---|
| **MIT / Apache 2.0** | Yes | Yes (no restriction) | Activepieces, Composio, Membrane, Trigger.dev |
| **Elastic License v2** | No (close to OSS) | Blocks competing managed services | Airbyte, Nango, Elasticsearch (since 2021) |
| **BSL (Business Source License)** | No, but converts to OSS after N years | Blocks managed services until conversion | Sentry, HashiCorp Terraform (since 2023), CockroachDB |
| **SSPL** | No | Forces source-disclosure of any SaaS using it | MongoDB, Elastic (briefly) |
| **Sustainable Use License** (n8n's) | No, "fair-code" | Free for internal use, blocks reselling | n8n |

### Why pure MIT/Apache is dangerous for commercial OSS

If you ship under MIT and grow, any cloud provider can launch a managed service of your product tomorrow and undercut you on price. **They benefit from your work without contributing back.** This happened to:
- MongoDB → AWS DocumentDB
- Elastic → AWS OpenSearch
- Redis → AWS ElastiCache

Each forced these companies into restrictive license changes (SSPL, Elastic v2). Better to start with the restrictive license and avoid the painful migration.

### Why Elastic v2 is the modern default

- Allows self-hosting (the product is genuinely OSS-shaped)
- Blocks "competing managed service" — the SaaS competitor threat that killed earlier MIT-licensed companies
- Industry-standard for OSS-with-commercial since 2021
- Less restrictive than SSPL (which scares contributors)
- Not "fair-code" non-OSI license (which confuses contributors)

### What the major players chose

- **n8n** — Sustainable Use License (their own fair-code license). Most restrictive of the "open" options.
- **Airbyte** — Elastic License v2 (some components), MIT (others). Hybrid.
- **Nango** — Elastic License v2.
- **Activepieces** — MIT.
- **Composio** — MIT.
- **Trigger.dev** — Apache 2.0.
- **Sentry** — BSL.

### For Donna

[06-deployment-and-self-hosting.md](06-deployment-and-self-hosting.md) commits to **Elastic License v2 (recommended)** for the first public release. The reasoning:
- Allows on-prem (committed to)
- Blocks competing Donna-as-a-Service launches
- Industry-standard
- Less restrictive than n8n's SUL (clearer for contributors)

**The license decision is deferred to first public release.** Until the repo goes public, the codebase remains private and the license can change without consequence.

---

## 9. Webhook reliability infrastructure

The often-missed piece. Webhooks are unreliable — providers retry on timeout, send duplicate events, miss events on outages. At scale, a dedicated webhook layer becomes valuable.

### What webhook gateways do

A webhook gateway sits between the provider and your app:

```
Slack ──webhook──→ [Webhook Gateway] ──→ Your app
                          │
                          ├─ Signature verification
                          ├─ Replay storage
                          ├─ Retry logic
                          ├─ Observability (which webhooks succeeded/failed)
                          └─ Dead-letter handling
```

### The major options

- **Hookdeck** — managed webhook gateway. Verifies signatures, retries, replays, observability. Free tier exists.
- **Convoy** (OSS) — self-host equivalent. Apache 2.0.
- **Svix** — mostly for *sending* webhooks (you sending to your customers), less relevant for *receiving*.

### When you need one

- **<5 integrations**: Don't bother. Your webhook handler handles its own signature verification + idempotency.
- **5–20 integrations**: Optional. The observability becomes valuable when something breaks.
- **20+ integrations**: Probably valuable. Especially if you have customer-facing webhooks (your app sending webhooks to customers' systems).
- **100+ integrations**: Definitely valuable. Otherwise you write 100 signature verifiers and 100 idempotency tables.

### Why Donna doesn't use one in v1

For Tier 1 (5-10 providers), the framework's `BaseWebhookHandler` plus `DeliveryPackage`'s `UniqueConstraint(workspace, provider, provider_item_id)` handles it (idempotency at the resulting-record level). Adding Hookdeck/Convoy makes sense at integration #20+, when:
- Multiple integrations have flaky webhook delivery
- Observability across providers becomes a real need
- The cost of running Hookdeck (or self-hosting Convoy) is justified

This is in the [05-integration-architecture.md](05-integration-architecture.md) staged migration list.

---

## 10. Decision framework: which path for your product

Distilled decision tree from everything above. Use this to evaluate any new product's integration strategy.

### Step 1 — What are integrations to you?

- **Integrations are infrastructure** (you need data from HRIS/CRM/etc. but they're not the product) → Use a unified API (Merge, Finch). Skip the rest of this framework.
- **Integrations are the product** (the value is what your product does WITH the integration data) → Continue.

### Step 2 — How many integrations long-term?

- **<5** → Build it all yourself. Frameworks are overkill.
- **5–30** → Build deep custom for all, with a strong internal framework. (Donna's current state.)
- **30–100** → Tier 1 deep custom (5-10), platform for the rest (Composio/Nango).
- **100+** → Tier 1 deep custom (5-10), AI action layer for ~90 (Composio), maybe sync platform for read-only long tail.

### Step 3 — Does the agent need to act in tools?

- **No, just read** → Code-first sync platform (Nango) or build your own
- **Yes** → AI agent action layer (Composio, Arcade) for tools where you don't need deep semantic understanding; deep custom for the ones where you do.

### Step 4 — What's the deployment story?

- **Cloud only** → Choose freely, including managed platforms.
- **On-premise required** → Avoid AWS-only services, use S3-compatible storage, plain workers, BYO OAuth flow. License decision becomes critical.
- **Hybrid** → Same code, configurable infra. The n8n model.

### Step 5 — What workflow engine?

- **Pure Django** → Celery (default), Django-Q (if Postgres-only)
- **Multi-language / startup velocity wins** → Inngest
- **Enterprise scale** → Temporal

### Step 6 — License decision

- **Closed-source SaaS** → No OSS license needed
- **Open-source with commercial** → Elastic v2 or BSL (default)
- **Permissive OSS for community ecosystem** → Apache 2.0 (accept the SaaS-competitor risk)
- **Avoid** → Pure MIT for integration-heavy commercial products (SaaS competitor risk)

### Step 7 — Staged migration

The most important insight: **don't pre-commit to platforms before feeling the pain they solve.** Build 3-5 integrations yourself first. The framework that emerges is the right framework. Then layer platforms underneath as concrete needs arrive.

This is the pattern Donna locked in: Fathom custom → Slack custom → Gmail/Linear/Drive custom → platform layer at #5-7 → workflow engine migration at ~#10 → silver layer evolution at ~#30.

---

## Sources

Research conducted during the Donna integration architecture sessions. Most-referenced sources:

- [Truto — Build vs Buy: The True Cost of Building SaaS Integrations In-House](https://truto.one/blog/build-vs-buy-the-true-cost-of-building-saas-integrations-in-house)
- [Truto — Merge vs Nango vs Alloy Automation: 2026 Architecture Comparison](https://truto.one/blog/merge-vs-nango-vs-alloy-automation-2026-architecture-comparison/)
- [Truto — Architecting AI Agents: LangGraph, LangChain, and the SaaS Integration Bottleneck](https://truto.one/blog/architecting-ai-agents-langgraph-langchain-and-the-saas-integration-bottleneck/)
- [Composio — Best AI agent integration platforms (2026)](https://composio.dev/content/ai-agent-integration-platforms)
- [Composio — Build vs. buy AI agent integrations: a 2026 decision framework](https://composio.dev/content/build-vs-buy-ai-agent-integrations)
- [StackOne — 120+ Agentic AI Tools Mapped Across 11 Categories (2026)](https://www.stackone.com/blog/ai-agent-tools-landscape-2026/)
- [Akka — Inngest vs. Temporal](https://akka.io/blog/inngest-vs-temporal)
- [Nango — Nango vs Merge](https://nango.dev/merge-dev-vs-nango)
- [chiefmartec — 4 layers of app integrations with SaaS platforms](https://chiefmartec.com/2019/04/4-layers-of-app-integrations-with-saas-platforms/)
- [Akmatori — Best Open Source MinIO Alternatives 2026](https://akmatori.com/blog/minio-alternatives-2026-comparison)
- [Cubbit — Top MinIO and Ceph S3 alternatives in 2025](https://medium.com/cubbit/top-minio-and-ceph-s3-alternatives-in-2025-european-gems-inside-b99aa4c6abb6)
- [Awesome self-hosted AWS alternatives — GitHub](https://github.com/fffaraz/awesome-selfhosted-aws)
- [Langfuse — Self-hosting documentation](https://langfuse.com/self-hosting)
- [Northflank — How to self-host n8n](https://northflank.com/blog/how-to-self-host-n8n-setup-architecture-and-pricing-guide)
- [Airbyte — Deploying Airbyte (deprecating Docker Compose)](https://docs.airbyte.com/platform/deploying-airbyte)
- [openalternative — ActivePieces: Open Source Alternative to n8n](https://openalternative.co/activepieces)
- [automationatlas — ActivePieces vs n8n 2026 Open-Source Automation Compared](https://automationatlas.io/answers/activepieces-vs-n8n-open-source-2026/)
