# Five Subsystems Overview

The Cortex layer is exactly five composable subsystems behind one
facade. Each owns one concern. Each is swappable.

```
                     CortexWriter           ← Facade. Single entry point.
                          │
            ┌─────────────┼─────────────┐
            │             │             │
      ┌─────▼─────┐  ┌────▼────┐  ┌─────▼──────┐
      │ 1. OCR    │  │ 2.      │  │ 3. Entity  │
      │ Service   │  │ Embed + │  │ Extract +  │
      │           │  │ Cluster │  │ Resolve    │
      └─────┬─────┘  └────┬────┘  └─────┬──────┘
            │             │             │
      ┌─────▼─────────────▼─────────────▼──────┐
      │ 4. Folder Resolver  +  5. Template     │
      │    Engine + Linter                     │
      └─────────────────┬───────────────────────┘
                        │
                  ┌─────▼──────┐
                  │ Repository │ ← Hides ORM. Atomic txn boundary.
                  └─────┬──────┘
                        │
                  ┌─────▼─────────┐
                  │ cortex_entity │ ← ONE table (Postgres = derived index)
                  └───────────────┘
```

## Subsystem 1 — OCR / markdownify

**Concern:** every source format (PDF, image, raw bytes, JSON) → uniform
markdown the rest of the pipeline can consume.

**Strategy interface:** `OCRStrategy.extract(path) → OCRResult`.

**Implementations (4 shipped):**

| Strategy | Handles | Notes |
|---|---|---|
| `PyMuPDF4LLMStrategy` | `.pdf` (text-native) | Fastest path |
| `MarkItDownStrategy` | `.docx/.pptx/.xlsx/.html/.eml/...` | Microsoft converter, widest format |
| `EasyOCRStrategy` | scans / phone photos | torch-based fallback |
| `LLMStrategy` (vision) | images, structured PDFs | Anthropic vision |

Selector `OCRFacade` picks order per mime type and falls back on failure.

Code: `donna/cortex/ocr.py` → shim around `donna/core/ocr/`.

Deep dive: [`../02 - subsystems/01-ocr.md`](../02%20-%20subsystems/01-ocr.md)

## Subsystem 2 — Embedding + clustering

**Concern:** group entities by latent topic so navigation emerges from
the data instead of hand-curated folders.

**Pieces:**

| Interface | Default impl | Role |
|---|---|---|
| `EmbeddingStrategy` | `BGESmallEmbedder` | text → 384-dim vector |
| `ClusterStrategy` | `HDBSCANClusterer` | nearest-centroid online + nightly batch |
| `ClusterNamerStrategy` | `HaikuNamer` | 5 samples → human-readable name via LiteLLM |

Composition: `ClusteringService` injects all three.

**Two modes:** cheap online assign on every write + nightly recluster
via Celery beat. Both scoped to `(workspace, client, project)`.

Code: `donna/cortex/embeddings.py`, `donna/cortex/clustering.py`.

Deep dive: [`../02 - subsystems/02-embedding-clustering.md`](../02%20-%20subsystems/02-embedding-clustering.md)

## Subsystem 3 — Entity extraction + resolution

**Concern:** for every Silver row we ingest, surface the people /
orgs / projects / concepts it mentions and bind them to typed entity
rows. Drives the "Acme universe" navigation.

**Pieces:**

| Interface | Default impl | Role |
|---|---|---|
| `EntityExtractor` (chain) | `CompositeExtractor` | Chain of Responsibility: Provider → GLiNER |
|   member | `ProviderMetadataExtractor` | host/sender/owner/participants from adapter metadata |
|   member | `GLiNERExtractor` (optional) | body-text NER |
| `EntityResolver` | `DeterministicResolver` | match-or-spawn against curated rows |

Spawned curated rows ship with full provenance: `author=donna`,
`source=cortex://spawn/<id>`, `confidence=medium`,
`body_md` ends with `Spawned by: cortex-resolver`.

Code: `donna/cortex/entities.py`.

Deep dive: [`../02 - subsystems/03-entity-extraction-resolver.md`](../02%20-%20subsystems/03-entity-extraction-resolver.md)

## Subsystem 4 — Folder resolver

**Concern:** every Silver row needs ONE canonical filesystem location
(the topical or temporal lens). Other axes are derived query views.

**Three lenses, one table:**

| Axis | Lens | Path shape |
|---|---|---|
| **Temporal** | meeting / email | `<scope>/meetings/YYYY/MM/` |
| **Topical** | doc / clip / note | `<scope>/<bucket>/` (clusters derived) |
| **Entity** | person / org / project / concept / decision | workspace root or `clients/<slug>/` |

Per-type `FolderResolver` plus a derived `DerivedNamespaceView` for
entity-axis queries.

Code: `donna/cortex/folders.py`.

Deep dive: [`../02 - subsystems/04-folder-resolvers.md`](../02%20-%20subsystems/04-folder-resolvers.md)

## Subsystem 5 — Template engine + linter

**Concern:** every type is rendered through a Jinja template that fits
to a strong convention. Predictable shape → fast agent comparison.

**Three aligned contracts per type:**

1. Pydantic frontmatter model (Pydantic extensions)
2. Jinja2 template (verbatim body + closed-vocab frontmatter + Source footer)
3. Closed Literal taxonomy (type + sub-discriminators)

**Linter** enforces R1-R10 from spec §7 + the §7.2 hard rejects before
the row is persisted.

Code: `donna/cortex/template_engine.py`, `donna/cortex/registry.py`,
`donna/cortex/linter.py`, `donna/cortex/templates/`.

Deep dive: [`../02 - subsystems/05-template-engine.md`](../02%20-%20subsystems/05-template-engine.md)

## How the five compose

`CortexWriter.write(dp)` is the only public method. It calls each
subsystem in a fixed sequence; the orchestrator owns no domain logic.

```python
class CortexWriter:
    def __init__(
        self,
        *,
        ocr: OCRService | None = None,
        embedder=None,
        clusterer=None,
        extractor: EntityExtractor | None = None,
        resolver: EntityResolver | None = None,
        registry: TemplateRegistry | None = None,
        engine: TemplateEngine | None = None,
        fitter: TemplateFitter | None = None,
        linter: FrontmatterLinter | None = None,
        repo: CortexEntityRepository | None = None,
        ...
    ): ...
```

Every collaborator is a Protocol → constructor-injected → unit-testable
with mocks → swappable per workspace.

The 11-step pipeline body is in [`02-cortexwriter-facade.md`](./02-cortexwriter-facade.md).

## Why this shape (the SOLID lens)

| Principle | Where it shows |
|---|---|
| **S — Single Responsibility** | Each subsystem owns one concern; `CortexWriter` only orchestrates. |
| **O — Open/Closed** | New OCR backend / clustering algo / template type = add a Strategy + register it; orchestrator code unchanged. |
| **L — Liskov** | Strategies are interchangeable at the interface level (no leaked implementation details). |
| **I — Interface Segregation** | Extractor, Resolver, Fitter, Folder Resolver are separate small interfaces. |
| **D — Dependency Inversion** | Orchestrator depends on Protocols; concrete strategies are constructor-injected. |

Plus design patterns:

| Pattern | Where |
|---|---|
| **Facade** | `CortexWriter` hides the 5 subsystems behind one method |
| **Strategy** | OCR backends, embedders, clusterers, extractors, resolvers, fitters, folder resolvers |
| **Registry** | `TemplateRegistry` discovers TypeSpecs at `apps.ready()` |
| **Chain of Responsibility** | `CompositeExtractor` chains Provider → GLiNER, dedupes |
| **Repository** | `CortexEntityRepository` hides Django ORM; atomic txn boundary |
| **Factory** | `OCRFacade.create_ocr()` builds the strategy stack lazily |
