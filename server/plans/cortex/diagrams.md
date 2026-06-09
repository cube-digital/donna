# Cortex — Architecture + Flow Diagrams

> Open this file in Obsidian / VSCode (Mermaid preview) / GitHub —
> all render Mermaid natively. Or paste a block into
> [mermaid.live](https://mermaid.live).

## 1. Architecture overview

End-to-end: external sources → bronze → Cortex pipeline → split
persistence (Postgres = derived index, SilverStorage = truth).

```mermaid
graph TB
    subgraph EXT["External"]
        F[Fathom]
        G[Gmail]
        D[Drive]
        S[Slack / Linear / future]
    end

    subgraph TASKS["Celery Tasks"]
        FT["fathom_ingest_meeting (P7 ✓)"]
        GT["gmail_ingest_message (P8 ✓)"]
        DT["drive (P8 — skipped)"]
        ST["others (future)"]
    end

    subgraph BRONZE["BRONZE Layer"]
        DS["default_storage<br/>S3 / FS / GCS / Azure"]
        DP[("DeliveryPackage<br/>(Postgres row)")]
    end

    subgraph CORTEX["CORTEX Layer — CortexWriter facade"]
        OCR["OCRService (P2)<br/>PyMuPDF · MarkItDown · EasyOCR · LLM"]
        EMB["Embedder<br/>(BGE-small + per-type sampler)"]
        CLU["Clusterer<br/>(HDBSCAN scoped)"]
        EXT2["Extractor<br/>(Provider + GLiNER)"]
        RES["Resolver<br/>(match-or-spawn)"]
        FOLD["FolderResolver<br/>(9 per-type)"]
        TPL["TemplateEngine<br/>(Jinja2 + 12 templates)"]
        LINT["FrontmatterLinter<br/>(R1-R10 + 13 reject codes)"]
        REPO["Repository<br/>(atomic txn)"]
    end

    subgraph PERSIST["Persistence (P0.14)"]
        PG[("Postgres<br/>cortex_entities<br/>= DERIVED index")]
        SS["SilverStorage<br/>default_storage<br/>= TRUTH<br/>cortex/&lt;ws&gt;/&lt;type&gt;/&lt;id&gt;.md"]
    end

    subgraph OPS["Maintenance"]
        TASKS2["recluster_fanout<br/>(nightly)"]
        TASKS3["reap_orphan_bodies<br/>(nightly)"]
        SYNC["cortex_sync<br/>(P11 ops command)"]
    end

    F --> FT
    G --> GT
    D --> DT
    S --> ST
    FT --> DS
    FT --> DP
    GT --> DS
    GT --> DP

    DP -- "CortexWriter.write(dp)" --> OCR
    OCR --> EMB
    EMB --> CLU
    CLU --> FOLD
    FOLD --> TPL
    TPL --> EXT2
    EXT2 --> RES
    RES --> LINT
    LINT --> REPO

    REPO -- "PG row + edges (atomic)" --> PG
    REPO -- "body file" --> SS
    PG <--> SS

    PG <-- "recompute" --> SYNC
    SS <-- "reap orphans" --> SYNC
    TASKS2 -- "nightly" --> PG
    TASKS3 -- "nightly" --> SS

    style BRONZE fill:#fff3cd
    style CORTEX fill:#d1ecf1
    style PERSIST fill:#d4edda
    style EXT fill:#f8d7da
    style OPS fill:#e2e3e5
```

---

## 2. Write flow — CortexWriter.write(dp) 11 steps

```mermaid
sequenceDiagram
    participant Conn as Connector Task
    participant W as CortexWriter
    participant OCR as OCRService
    participant Reg as Registry
    participant Lint as Linter
    participant Fit as Fitter
    participant Emb as Embedder<br/>(sampler-aware)
    participant Clu as Clusterer
    participant Fold as FolderResolver
    participant Tpl as TemplateEngine
    participant Ext as Extractor
    participant Res as Resolver
    participant Repo as Repository
    participant SS as SilverStorage
    participant PG as Postgres

    Conn->>W: write(DeliveryPackage)
    W->>OCR: 1. body_md
    OCR-->>W: markdown
    W->>Reg: 2. get(type) → TypeSpec
    W->>W: 3. build extensions
    W->>Lint: 4. nav fields ok?
    alt missing nav
        W->>Fit: fit(body, fit_model)
        Fit-->>W: filled fields
    end
    W->>Emb: 5. embed_entity(title, body, sampler)
    Emb-->>W: vec[384]
    W->>Clu: assign(vec, scope)
    Clu-->>W: cluster_id, name
    W->>Fold: 6. canonical_path(...)
    Fold-->>W: parent_path + slug
    W->>Tpl: 7. render(spec, extensions, body)
    Tpl-->>W: body_md_final
    W->>W: 8. build CortexEntity (unsaved)
    W->>Ext: 9. extract candidates
    Ext-->>W: persons / orgs / projects
    loop each candidate
        W->>Res: resolve(candidate, scope)
        Res-->>W: target_id
    end
    W->>Lint: 10. check(entity, body_md=body_md_final)
    W->>Repo: 11. save_with_reverse_edges(entity, body_bytes)
    Note over Repo,PG: BEGIN
    Repo->>PG: INSERT row (body=NULL)
    Repo->>SS: write file via FileField
    Repo->>PG: UPDATE entity.body = path
    loop sources / supersedes / contradicts
        Repo->>PG: SELECT FOR UPDATE target<br/>UPDATE reverse edge
    end
    Note over Repo,PG: COMMIT
    Repo-->>W: persisted CortexEntity
    W-->>Conn: entity
```

---

## 3. Three reverse-edge writers (atomic in same txn)

```mermaid
graph LR
    NEW[New Entity M]

    NEW -- "M.sources = [D]" --> A1[_append_applied_in]
    NEW -- "M.supersedes = [V1]" --> A2[_assign_superseded_by]
    NEW -- "M.contradicts = [E1]" --> A3[_append_contradicts]

    A1 -- "SELECT FOR UPDATE D<br/>D.applied_in += M<br/>UPDATE" --> D[(Target D<br/>e.g. ADR)]
    A2 -- "SELECT FOR UPDATE V1<br/>V1.superseded_by = M<br/>UPDATE" --> V1[(Target V1<br/>old doc)]
    A3 -- "SELECT FOR UPDATE E1<br/>E1.contradicts += M<br/>UPDATE (symmetric)" --> E1[(Target E1<br/>conflicting email)]

    style NEW fill:#48dbfb
    style D fill:#feca57
    style V1 fill:#feca57
    style E1 fill:#feca57
```

---

## 4. Read flow — agent answers user question

User: *"What did we discuss with Acme last week?"*

```mermaid
sequenceDiagram
    participant U as User
    participant Agent as Donna chat agent
    participant Emb as Embedder
    participant PG as Postgres<br/>(cortex_entities)
    participant SS as SilverStorage
    participant LLM as Synthesis LLM<br/>(Sonnet/Haiku)

    U->>Agent: question
    Agent->>Agent: resolve "Acme" → acme_uuid
    Agent->>Emb: embed(question)
    Emb-->>Agent: q_vec[384]

    par Three lenses (cheap, no LLM)
        Agent->>PG: entity_refs @> [acme_uuid]<br/>AND occurred_at >= last_week
        Agent->>PG: ORDER BY doc_embedding <=> q_vec LIMIT 20
        Agent->>PG: WHERE parent_path = "meetings/2026/06"
    end
    PG-->>Agent: top-K rows (metadata + path)

    loop top-5 candidates
        Agent->>SS: entity.body.open() byte-range
        SS-->>Agent: body_md (verbatim)
    end

    Agent->>LLM: synthesize(question, [bodies], cite_ids)
    LLM-->>Agent: answer + citations
    Agent-->>U: response
```

Key: bodies fetched from SilverStorage ONLY for the top-K candidates,
not the whole workspace. Postgres handles filtering; storage handles
content; LLM only synthesizes.

---

## 5. Storage tiers — what lives where

```mermaid
graph TB
    subgraph HOT["HOT — Postgres column"]
        H1[id · type · author · source · content_hash]
        H2[occurred_at · created_at · updated_at]
        H3[workspace_id · client_id · project_id]
        H4[cluster_id · doc_embedding · confidence]
        H5[title · body_byte_size]
        H6[entity_refs · sources · cross_refs · supersedes · related]
        H7[applied_in · superseded_by · contradicts]
        H8[extensions JSONB]
        H9[body FileField pointer]
    end

    subgraph COLD["COLD — SilverStorage file"]
        C1[Rendered markdown body<br/>YAML frontmatter + verbatim content + Source footer]
    end

    subgraph BRONZE["BRONZE — default_storage"]
        B1[Raw provider blob<br/>Fathom JSON, Gmail JSON, Drive PDF, etc.]
    end

    H9 -.points to.-> C1
    H1 -.bronze_storage_key.-> B1

    style HOT fill:#f8d7da
    style COLD fill:#d4edda
    style BRONZE fill:#fff3cd
```

---

## 6. Per-type embedding sampler choice

```mermaid
graph LR
    subgraph TYPES["Entity Type"]
        T1[chat · email · ticket]
        T2[meeting]
        T3[doc]
        T4[clip · note · person · org · project · concept · decision]
    end

    subgraph SAMPLERS["Sampler"]
        S1[head_heavy_sampler<br/>70/20/10 head/mid/tail]
        S2[uniform_sampler<br/>4 even windows]
        S3[head_tail_sampler<br/>40/60 head/tail · skip middle]
        S4[fixed_window_sampler<br/>40/30/30 default]
    end

    T1 --> S1
    T2 --> S2
    T3 --> S3
    T4 --> S4

    S1 --> E[Embedder<br/>BGE-small<br/>≤ 1900 chars input<br/>512 token context]
    S2 --> E
    S3 --> E
    S4 --> E

    style TYPES fill:#d1ecf1
    style SAMPLERS fill:#feca57
    style E fill:#48dbfb
```

---

## 7. Acme unified namespace — three axes, one row

Same meeting, three different lenses:

```mermaid
graph TB
    M["Meeting Row<br/>type=meeting<br/>cluster_id=xyz<br/>parent_path=meetings/2026/06<br/>entity_refs=[alice, bob, acme]"]

    subgraph TOP["Topical axis"]
        TP["Folder: 01 - Clusters/Customer Onboarding"]
    end

    subgraph TEM["Temporal axis"]
        TE["Folder: meetings/2026/06/<br/>2026-06-03-acme-kickoff.md"]
    end

    subgraph ENT["Entity axis (derived query)"]
        EN["WHERE entity_refs @> [acme_uuid]<br/>→ this row + emails + docs + tickets<br/>all about Acme"]
    end

    M --> TP
    M --> TE
    M --> EN

    style M fill:#48dbfb
```

---

## 8. ADR supersession chain

```mermaid
graph LR
    A[ADR-W001<br/>'Postgres only'<br/>2026-05-01]
    B[ADR-W002<br/>'Postgres + pgvector'<br/>2026-06-03]
    C[ADR-W003<br/>'Files + Postgres derived'<br/>future]

    A -. "B.supersedes = [A]" .-> B
    B -- "A.superseded_by = B<br/>(auto-written by repo)" --> A
    B -. "C.supersedes = [B]" .-> C
    C -- "B.superseded_by = C" --> B

    style A fill:#ff6b6b
    style B fill:#feca57
    style C fill:#48dbfb
```

Each ADR row immutable. Agent reading A sees `superseded_by` → walks
chain to current truth C. No deletion; full history preserved.

---

## How to view these

| Viewer | Action |
|---|---|
| Obsidian | open file — Mermaid renders inline in preview pane |
| VSCode | install "Markdown Preview Mermaid Support" → open preview |
| GitHub | open the file on the web — Mermaid renders natively |
| Mermaid Live | paste any block into [mermaid.live](https://mermaid.live) |
| CLI | `npx -p @mermaid-js/mermaid-cli mmdc -i diagrams.md -o diagrams.svg` |
