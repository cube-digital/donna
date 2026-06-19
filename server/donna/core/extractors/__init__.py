"""Core extractor primitives — reusable across apps.

Pure-Python extractors (no app-model dependencies). The
``entities`` submodule provides Protocol + Composite + concrete
``ProviderMetadataExtractor`` / ``GLiNERExtractor`` for use by the
cortex pipeline and any future consumer (e.g. ad-hoc body NER from
a Vault note).
"""
