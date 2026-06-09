"""
Cortex layer — the structured, queryable, cluster-organised layer
that sits between Bronze (DeliveryPackage blobs) and the future Graph
layer.

Single Postgres table (``cortex_entities``) is the source of truth.
Five subsystems compose into one ``CortexWriter`` facade:

1. OCR (``donna.cortex.ocr``)
2. Embed + cluster (``donna.cortex.embeddings`` + ``donna.cortex.clustering``)
3. Entity extract + resolve (``donna.cortex.entities``)
4. Folder resolver (``donna.cortex.folders``)
5. Template application (``donna.cortex.template_engine`` + registry + linter)

See ``server/plans/peppy-sleeping-moler.md`` for the design.
"""
default_app_config = "donna.cortex.apps.CortexConfig"
